"""
Rule-Watcher
============
Prüft alle 10 Sekunden alle aktiven Regeln und schaltet Ziel-Maschinen
basierend auf kombinierten Bedingungen (AND-Logik).

Zustandsautomat pro Regel:
  idle      → alle Bedingungen falsch, Maschine AUS
  on        → alle Bedingungen wahr, Maschine EIN
  countdown → Bedingungen nicht mehr alle wahr, Nachlaufzeit läuft

Bedingungstypen:
  power          – Quell-Maschine zieht >= power_on_w (hysterese: power_off_w)
  schedule       – aktuelle Zeit im Fenster + richtiger Wochentag
  room_open      – system_settings.room_open == True
  session_active – mind. eine Maschine hat aktive Session
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func

from app.models import AutomationRule, RuleCondition, Machine, MachineSession, LogType, SessionEndedBy
from app.services.plug import get_plug_status, switch_all_machine_plugs
from app.services.session import start_manager_session, end_session
from app.services import logger as log_svc
from app.services.system_settings import get_system_settings
from app.services.room import open_room, close_room
from app.config import APP_TIMEZONE

log = logging.getLogger(__name__)

# {rule_id: "idle" | "on" | "countdown"}
_state:           dict[int, str]      = {}
# {rule_id: datetime}  — wann Countdown begann
_countdown_start: dict[int, datetime] = {}


async def rule_watcher(app):
    from app.database import AsyncSessionLocal
    while True:
        await asyncio.sleep(10)
        try:
            async with AsyncSessionLocal() as db:
                settings  = await get_system_settings(db)
                rules_res = await db.execute(
                    select(AutomationRule).where(AutomationRule.enabled == True)
                )
                for rule in rules_res.scalars().all():
                    try:
                        await _process(rule, settings.room_open, db)
                    except Exception as e:
                        log.error(f"Regel {rule.id} Fehler: {e}")
        except Exception as e:
            log.error(f"Rule-Watcher Fehler: {e}")


async def _evaluate_conditions(rule_id: int, state: str, room_open: bool, db) -> bool:
    """Gibt True zurück wenn ALLE Bedingungen der Regel erfüllt sind."""
    conds_res = await db.execute(
        select(RuleCondition).where(RuleCondition.rule_id == rule_id)
    )
    conds = conds_res.scalars().all()
    if not conds:
        return False

    now_local = datetime.now(APP_TIMEZONE)
    weekday   = now_local.isoweekday()
    now_time  = now_local.time().replace(second=0, microsecond=0)

    for c in conds:
        if c.type == "power":
            if not c.source_machine_id:
                return False
            src_res = await db.execute(select(Machine).where(Machine.id == c.source_machine_id))
            src = src_res.scalar_one_or_none()
            if not src or src.plug_type == "none" or not src.plug_ip:
                return False
            status = await get_plug_status(src)
            power  = status.get("power_w")
            if power is None:
                return False
            # Hysterese: höhere Schwelle zum Einschalten, niedrigere zum Halten
            threshold = c.power_on_w if state == "idle" else c.power_off_w
            if power < threshold:
                return False

        elif c.type == "schedule":
            allowed = {int(d) for d in c.days.split(",") if d.strip().isdigit()}
            if weekday not in allowed:
                return False
            if not (c.time_on <= now_time < c.time_off):
                return False

        elif c.type == "room_open":
            if not room_open:
                return False

        elif c.type == "session_active":
            cnt_res = await db.execute(
                select(func.count()).select_from(Machine)
                .where(Machine.session_started_at != None)
            )
            if (cnt_res.scalar() or 0) == 0:
                return False

    return True


async def _process(rule: AutomationRule, room_open: bool, db) -> None:
    state   = _state.get(rule.id, "idle")
    now     = datetime.utcnow()
    all_met = await _evaluate_conditions(rule.id, state, room_open, db)

    action = rule.action_type or "machine"

    # ── Raum-Aktionen (einmalig feuern, kein Countdown) ──────────────────────
    if action in ("room_open", "room_close"):
        if all_met and state == "idle":
            if action == "room_open":
                await open_room(db, reason="Automation")
                log.info(f"Regel {rule.id} '{rule.name}': Raum geöffnet")
            else:
                await close_room(db, reason="Automation")
                log.info(f"Regel {rule.id} '{rule.name}': Raum geschlossen")
            _state[rule.id] = "on"
        elif not all_met and state == "on":
            _state[rule.id] = "idle"
        return

    # ── Maschinen-Aktion (bestehende Logik) ───────────────────────────────────
    if all_met:
        _countdown_start.pop(rule.id, None)

        if state != "on":
            tgt_res = await db.execute(select(Machine).where(Machine.id == rule.target_machine_id))
            tgt = tgt_res.scalar_one_or_none()
            if not tgt:
                return
            ok, msg = await switch_all_machine_plugs(tgt, "on", db)
            if ok:
                _state[rule.id] = "on"
                log.info(f"Regel {rule.id} '{rule.name}': {tgt.name} EIN")
                tgt_id = tgt.id
                await log_svc.log(db, LogType.rule_on,
                                  f"Regel '{rule.name or rule.id}': {tgt.name} EIN",
                                  machine_id=tgt_id)
                tgt = (await db.execute(select(Machine).where(Machine.id == tgt_id))).scalar_one_or_none()
                if tgt and not tgt.session_started_at:
                    await start_manager_session(db, tgt, user_id=None, source="automation")
            else:
                log.warning(f"Regel {rule.id}: Einschalten fehlgeschlagen — {msg}")

    else:
        if state in ("on", "countdown"):
            if rule.id not in _countdown_start:
                _countdown_start[rule.id] = now
            _state[rule.id] = "countdown"
            elapsed = (now - _countdown_start[rule.id]).total_seconds()
            if elapsed >= rule.off_delay_sec:
                tgt_res = await db.execute(select(Machine).where(Machine.id == rule.target_machine_id))
                tgt = tgt_res.scalar_one_or_none()
                if tgt:
                    ok, msg = await switch_all_machine_plugs(tgt, "off", db)
                    if ok:
                        _state[rule.id] = "idle"
                        _countdown_start.pop(rule.id, None)
                        log.info(f"Regel {rule.id} '{rule.name}': {tgt.name} AUS (nach {elapsed:.0f}s)")
                        tgt_id = tgt.id
                        await log_svc.log(db, LogType.rule_off,
                                          f"Regel '{rule.name or rule.id}': {tgt.name} AUS",
                                          machine_id=tgt_id)
                        tgt = (await db.execute(select(Machine).where(Machine.id == tgt_id))).scalar_one_or_none()
                        if tgt and tgt.session_started_at:
                            await end_session(db, tgt, ended_by=SessionEndedBy.system)
                    else:
                        log.warning(f"Regel {rule.id}: Ausschalten fehlgeschlagen — {msg}")
        else:
            _state[rule.id] = "idle"


def get_rule_states() -> dict:
    result = {}
    now = datetime.utcnow()
    for rule_id, state in _state.items():
        countdown_sec = None
        if state == "countdown" and rule_id in _countdown_start:
            countdown_sec = round((now - _countdown_start[rule_id]).total_seconds())
        result[rule_id] = {"state": state, "countdown_sec": countdown_sec}
    return result
