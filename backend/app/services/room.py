"""
Raum-Öffnungs- und Schliesslogik.

close_room(): schliesst den Raum und schaltet alle Maschinen mit force_off_on_close=True aus.
open_room():  öffnet den Raum.
"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Machine, LogType, SessionEndedBy
from app.services.plug import switch_all_machine_plugs
from app.services.session import end_session
from app.services.system_settings import get_system_settings
from app.services import logger as log_svc


async def open_room(db: AsyncSession, user_id: int | None = None, reason: str = "manuell") -> None:
    s = await get_system_settings(db)
    s.room_open = True
    s.room_open_since = datetime.utcnow()
    await db.commit()
    await log_svc.log(db, LogType.room_opened,
                      f"Raum geöffnet ({reason})", user_id=user_id)


async def close_room(db: AsyncSession, user_id: int | None = None, reason: str = "manuell") -> None:
    s = await get_system_settings(db)
    s.room_open = False
    s.room_open_since = None
    await db.commit()
    await log_svc.log(db, LogType.room_closed,
                      f"Raum geschlossen ({reason})", user_id=user_id)

    # Maschinen mit force_off_on_close ausschalten
    res = await db.execute(
        select(Machine).where(Machine.force_off_on_close == True)
    )
    for machine in res.scalars().all():
        try:
            if machine.plug_type != "none" and machine.plug_ip:
                await switch_all_machine_plugs(machine, "off", db)
            if machine.session_started_at:
                # machine nach commit neu laden (plug-switch hat commit ausgelöst)
                m2 = (await db.execute(
                    select(Machine).where(Machine.id == machine.id)
                )).scalar_one_or_none()
                if m2 and m2.session_started_at:
                    await end_session(db, m2, ended_by=SessionEndedBy.system)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"force_off_on_close Fehler ({machine.name}): {e}")
