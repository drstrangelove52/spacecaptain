"""
Automation-Watcher
==================
Pollt die Leistungsaufnahme von Quell-Maschinen und schaltet
Ziel-Maschinen automatisch ein/aus basierend auf konfigurierten Schwellwerten.

Zustandsautomat pro Automation:
  idle     → Quelle unter Ein-Schwelle, Ziel ist AUS
  on       → Quelle über Ein-Schwelle, Ziel ist EIN
  countdown→ Quelle unter Aus-Schwelle, Ziel ist noch EIN, Countdown läuft
"""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from app.models import MachineAutomation, Machine, LogType
from app.services.plug import get_plug_status, switch_all_machine_plugs
from app.services import logger as log_svc

log = logging.getLogger(__name__)

# Globaler Status: {automation_id: "idle"|"on"|"countdown"}
_state:            dict[int, str]      = {}
# Countdown-Start: {automation_id: datetime}
_countdown_start:  dict[int, datetime] = {}


async def automation_watcher(app):
    """Läuft alle 10 Sekunden und prüft alle aktiven Automationen."""
    from app.database import AsyncSessionLocal

    while True:
        await asyncio.sleep(10)
        try:
            async with AsyncSessionLocal() as db:
                res = await db.execute(
                    select(MachineAutomation).where(MachineAutomation.enabled == True)
                )
                autos = res.scalars().all()

                for a in autos:
                    try:
                        await _process(a, db)
                    except Exception as e:
                        log.error(f"Automation {a.id} Fehler: {e}")

        except Exception as e:
            log.error(f"Automation-Watcher Fehler: {e}")


async def _process(a: MachineAutomation, db) -> None:
    src_res = await db.execute(select(Machine).where(Machine.id == a.source_machine_id))
    src = src_res.scalar_one_or_none()
    if not src or src.plug_type == "none" or not src.plug_ip:
        return

    status = await get_plug_status(src)
    power = status.get("power_w")
    if power is None:
        return

    state = _state.get(a.id, "idle")
    now = datetime.utcnow()

    if power >= a.on_threshold_w:
        # Countdown abbrechen
        _countdown_start.pop(a.id, None)

        if state != "on":
            # Ziel einschalten
            tgt_res = await db.execute(select(Machine).where(Machine.id == a.target_machine_id))
            tgt = tgt_res.scalar_one_or_none()
            if tgt:
                ok, msg = await switch_all_machine_plugs(tgt, "on", db)
                if ok:
                    _state[a.id] = "on"
                    log.info(f"Automation {a.id}: {src.name} → {tgt.name} EIN ({power:.0f}W ≥ {a.on_threshold_w}W)")
                    await log_svc.log(
                        db, LogType.plug_on,
                        f"Automation: {src.name} → {tgt.name} EIN ({power:.0f} W)",
                        machine_id=tgt.id,
                    )
                else:
                    log.warning(f"Automation {a.id}: Einschalten fehlgeschlagen — {msg}")
                    await log_svc.log(
                        db, LogType.error,
                        f"Automation: {src.name} → {tgt.name} EIN fehlgeschlagen — {msg}",
                        machine_id=tgt.id,
                    )

    elif power < a.off_threshold_w:
        if state in ("on", "countdown"):
            if a.id not in _countdown_start:
                _countdown_start[a.id] = now
                _state[a.id] = "countdown"
            else:
                elapsed = (now - _countdown_start[a.id]).total_seconds()
                if elapsed >= a.off_delay_sec:
                    tgt_res = await db.execute(select(Machine).where(Machine.id == a.target_machine_id))
                    tgt = tgt_res.scalar_one_or_none()
                    if tgt:
                        ok, msg = await switch_all_machine_plugs(tgt, "off", db)
                        if ok:
                            _state[a.id] = "idle"
                            _countdown_start.pop(a.id, None)
                            log.info(f"Automation {a.id}: {src.name} → {tgt.name} AUS (nach {elapsed:.0f}s Nachlauf)")
                            await log_svc.log(
                                db, LogType.plug_off,
                                f"Automation: {src.name} → {tgt.name} AUS (Nachlauf {elapsed:.0f}s)",
                                machine_id=tgt.id,
                            )
                        else:
                            log.warning(f"Automation {a.id}: Ausschalten fehlgeschlagen — {msg}")
                            await log_svc.log(
                                db, LogType.error,
                                f"Automation: {src.name} → {tgt.name} AUS fehlgeschlagen — {msg}",
                                machine_id=tgt.id,
                            )

    else:
        # Zwischen Ein- und Ausschaltschwelle: Countdown abbrechen, Zustand beibehalten
        if state == "countdown":
            _countdown_start.pop(a.id, None)
            _state[a.id] = "on"


def get_automation_states() -> dict[int, dict]:
    """Gibt aktuellen Watcher-Status zurück (für API/Frontend)."""
    result = {}
    now = datetime.utcnow()
    for auto_id, state in _state.items():
        countdown_sec = None
        if state == "countdown" and auto_id in _countdown_start:
            countdown_sec = round((now - _countdown_start[auto_id]).total_seconds())
        result[auto_id] = {"state": state, "countdown_sec": countdown_sec}
    return result
