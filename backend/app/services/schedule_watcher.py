"""
Schedule-Watcher
================
Pollt jede Minute und schaltet Geräte basierend auf Zeitplänen.

Bedingungen pro Zeitplan:
  - Heutiger Wochentag ist in schedule.days (1=Mo, 7=So)
  - Aktuelle Lokalzeit liegt zwischen time_on und time_off
  - Wenn require_room_open=True: system_settings.room_open muss True sein

Zustand pro (schedule_id, datum): "idle" | "on" | "off"
"""
import asyncio
import logging
from datetime import datetime, date

from sqlalchemy import select

from app.models import DeviceSchedule, Machine, LogType
from app.services.plug import switch_all_machine_plugs
from app.services.session import start_manager_session, end_session
from app.services import logger as log_svc
from app.services.system_settings import get_system_settings
from app.models import SessionEndedBy
from app.config import APP_TIMEZONE

log = logging.getLogger(__name__)

# {schedule_id: (date_str, "idle"|"on"|"off")}
_state: dict[int, tuple[str, str]] = {}


async def schedule_watcher(app):
    from app.database import AsyncSessionLocal
    while True:
        await asyncio.sleep(60)
        try:
            async with AsyncSessionLocal() as db:
                settings = await get_system_settings(db)
                res = await db.execute(
                    select(DeviceSchedule).where(DeviceSchedule.enabled == True)
                )
                schedules = res.scalars().all()
                for s in schedules:
                    try:
                        await _process(s, settings.room_open, db)
                    except Exception as e:
                        log.error(f"Zeitplan {s.id} Fehler: {e}")
        except Exception as e:
            log.error(f"Schedule-Watcher Fehler: {e}")


async def _process(s: DeviceSchedule, room_open: bool, db) -> None:
    now_local = datetime.now(APP_TIMEZONE)
    today_str = now_local.strftime("%Y-%m-%d")
    weekday = now_local.isoweekday()  # 1=Mo, 7=So

    prev_date, state = _state.get(s.id, ("", "idle"))
    if prev_date != today_str:
        state = "idle"
        _state[s.id] = (today_str, "idle")

    # Tages-Check
    allowed_days = {int(d) for d in s.days.split(",") if d.strip().isdigit()}
    if weekday not in allowed_days:
        return

    now_time = now_local.time().replace(second=0, microsecond=0)
    in_window = s.time_on <= now_time < s.time_off

    if in_window and state == "idle":
        if s.require_room_open and not room_open:
            return  # Raum ist zu
        tgt_res = await db.execute(select(Machine).where(Machine.id == s.machine_id))
        tgt = tgt_res.scalar_one_or_none()
        if not tgt:
            return
        ok, msg = await switch_all_machine_plugs(tgt, "on", db)
        if ok:
            _state[s.id] = (today_str, "on")
            log.info(f"Zeitplan {s.id}: {tgt.name} EIN ({now_time})")
            tgt_id = tgt.id
            await log_svc.log(db, LogType.schedule_on,
                              f"Zeitplan '{s.name or s.id}': {tgt.name} EIN",
                              machine_id=tgt_id)
            tgt = (await db.execute(select(Machine).where(Machine.id == tgt_id))).scalar_one_or_none()
            if tgt and not tgt.session_started_at:
                await start_manager_session(db, tgt, user_id=None, source="schedule")
        else:
            log.warning(f"Zeitplan {s.id}: Einschalten fehlgeschlagen — {msg}")

    elif not in_window and state == "on":
        tgt_res = await db.execute(select(Machine).where(Machine.id == s.machine_id))
        tgt = tgt_res.scalar_one_or_none()
        if not tgt:
            return
        ok, msg = await switch_all_machine_plugs(tgt, "off", db)
        if ok:
            _state[s.id] = (today_str, "off")
            log.info(f"Zeitplan {s.id}: {tgt.name} AUS ({now_time})")
            tgt_id = tgt.id
            await log_svc.log(db, LogType.schedule_off,
                              f"Zeitplan '{s.name or s.id}': {tgt.name} AUS",
                              machine_id=tgt_id)
            tgt = (await db.execute(select(Machine).where(Machine.id == tgt_id))).scalar_one_or_none()
            if tgt and tgt.session_started_at:
                await end_session(db, tgt, ended_by=SessionEndedBy.system)
        else:
            log.warning(f"Zeitplan {s.id}: Ausschalten fehlgeschlagen — {msg}")


def get_schedule_states() -> dict[int, dict]:
    result = {}
    for sid, (date_str, state) in _state.items():
        result[sid] = {"date": date_str, "state": state}
    return result
