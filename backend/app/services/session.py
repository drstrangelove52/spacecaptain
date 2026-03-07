"""
Machine Session Service
"""
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import asyncio
import logging

from app.models import Machine, MachineSession, SessionEndedBy, LogType
from app.services.plug import switch_plug, get_plug_status
from app.services import logger as log_svc

log = logging.getLogger(__name__)

# Globaler Leerlauf-Status: {machine_id: datetime seit wann im Leerlauf}
# Wird vom idle_watcher befüllt und von der API gelesen
idle_since_global: dict[int, datetime] = {}


async def start_session(db: AsyncSession, machine: Machine, guest_id: int) -> MachineSession:
    """Startet eine neue Nutzungssession. Schreibt direkt per UPDATE in die DB."""
    # Offene Session abschließen
    if machine.current_guest_id:
        await end_session(db, machine, ended_by=SessionEndedBy.system)

    now = datetime.utcnow()

    # Session-Eintrag anlegen
    session = MachineSession(
        machine_id=machine.id,
        guest_id=guest_id,
        started_at=now,
    )
    db.add(session)

    # Machine direkt per UPDATE schreiben — umgeht SQLAlchemy-Cache-Probleme
    await db.execute(
        update(Machine)
        .where(Machine.id == machine.id)
        .values(current_guest_id=guest_id, session_manager_id=None, session_started_at=now)
    )

    # In-memory Objekt auch aktualisieren
    machine.current_guest_id = guest_id
    machine.session_manager_id = None
    machine.session_started_at = now

    await db.commit()
    await db.refresh(session)
    log.info(f"Session gestartet: machine_id={machine.id}, guest_id={guest_id}")
    return session


async def start_manager_session(db: AsyncSession, machine: Machine, user_id: int | None) -> MachineSession:
    """Startet eine Manager-Session (kein Gast, aber Idle-Policy gilt)."""
    # Offene Session abschliessen
    if machine.session_started_at:
        await end_session(db, machine, ended_by=SessionEndedBy.system)

    now = datetime.utcnow()
    session = MachineSession(machine_id=machine.id, guest_id=None, manager_id=user_id, started_at=now)
    db.add(session)

    await db.execute(
        update(Machine)
        .where(Machine.id == machine.id)
        .values(current_guest_id=None, session_manager_id=user_id, session_started_at=now)
    )
    machine.current_guest_id = None
    machine.session_manager_id = user_id
    machine.session_started_at = now

    await db.commit()
    await db.refresh(session)
    log.info(f"Manager-Session gestartet: machine_id={machine.id}, user_id={user_id}")
    return session


async def end_session(
    db: AsyncSession,
    machine: Machine,
    ended_by: SessionEndedBy = SessionEndedBy.guest,
    energy_wh: float = None,
) -> MachineSession | None:
    """Beendet die aktive Session einer Maschine."""
    result = await db.execute(
        select(MachineSession).where(
            MachineSession.machine_id == machine.id,
            MachineSession.ended_at == None,
        ).order_by(MachineSession.started_at.desc())
    )
    session = result.scalars().first()

    now = datetime.utcnow()
    added_hours = 0.0
    if session:
        session.ended_at = now
        session.ended_by = ended_by
        if session.started_at:
            session.duration_min = round((now - session.started_at).total_seconds() / 60, 2)
            added_hours = round((now - session.started_at).total_seconds() / 3600, 4)
        if energy_wh is not None:
            session.energy_wh = round(energy_wh, 3)

    # Machine direkt per UPDATE zurücksetzen + total_hours inkrementieren
    await db.execute(
        update(Machine)
        .where(Machine.id == machine.id)
        .values(
            current_guest_id=None,
            session_manager_id=None,
            session_started_at=None,
            total_hours=Machine.total_hours + added_hours,
        )
    )
    machine.current_guest_id = None
    machine.session_manager_id = None
    machine.session_started_at = None
    machine.total_hours = (machine.total_hours or 0.0) + added_hours

    await db.commit()
    log.info(f"Session beendet: machine_id={machine.id}, by={ended_by}")

    # Nächsten in der Warteliste benachrichtigen
    try:
        from app.services.queue_service import notify_next_in_queue
        from app.services.system_settings import get_system_settings
        sys_settings = await get_system_settings(db)
        await notify_next_in_queue(db, machine.id, sys_settings.queue_reservation_minutes)
    except Exception as e:
        log.error(f"Queue-Benachrichtigung fehlgeschlagen: {e}")

    return session


async def idle_watcher(app):
    """Prüft alle 60s ob Maschinen im Leerlauf sind und schaltet sie ab."""
    from app.database import AsyncSessionLocal

    # Lokaler Alias auf das globale Dict
    idle_since = idle_since_global

    while True:
        await asyncio.sleep(60)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Machine).where(
                        Machine.status == "online",
                        Machine.plug_type != "none",
                        Machine.idle_power_w != None,
                        Machine.idle_timeout_min != None,
                        Machine.session_started_at != None,  # Gast- UND Manager-Sessions
                    )
                )
                machines = result.scalars().all()

                for m in machines:
                    status = await get_plug_status(m)
                    power = status.get("power_w")

                    if power is None:
                        idle_since.pop(m.id, None)
                        continue

                    if power <= m.idle_power_w:
                        if m.id not in idle_since:
                            idle_since[m.id] = datetime.utcnow()
                        else:
                            idle_min = (datetime.utcnow() - idle_since[m.id]).total_seconds() / 60
                            if idle_min >= m.idle_timeout_min:
                                log.info(f"Idle-Timeout: {m.name} nach {idle_min:.1f} min")
                                ok, msg = await switch_plug(m, "off")
                                # Energie berechnen (power bekannt, Laufzeit aus session_started_at)
                                energy_wh = None
                                if m.session_started_at and power is not None:
                                    duration_h = (datetime.utcnow() - m.session_started_at).total_seconds() / 3600
                                    energy_wh = power * duration_h
                                await end_session(db, m, ended_by=SessionEndedBy.idle_timeout, energy_wh=energy_wh)
                                await log_svc.log(
                                    db, LogType.idle_off,
                                    f"Leerlauf-Abschaltung: {m.name} nach {idle_min:.0f} min — {msg}",
                                    machine_id=m.id,
                                    meta={"power_w": power, "idle_min": idle_min}
                                )
                                idle_since.pop(m.id, None)
                    else:
                        idle_since.pop(m.id, None)

        except Exception as e:
            log.error(f"Idle-Watcher Fehler: {e}")


async def queue_watcher(app):
    """Prüft alle 60s auf abgelaufene Queue-Benachrichtigungen und rückt vor."""
    from app.database import AsyncSessionLocal
    from app.services.queue_service import expire_stale_notifications
    from app.services.system_settings import get_system_settings

    while True:
        await asyncio.sleep(60)
        try:
            async with AsyncSessionLocal() as db:
                sys_settings = await get_system_settings(db)
                await expire_stale_notifications(db, sys_settings.queue_reservation_minutes)
        except Exception as e:
            log.error(f"Queue-Watcher Fehler: {e}")


async def plug_watcher(app):
    """
    Pollt den echten Schaltzustand jeder Maschine gemäss plug_poll_interval_sec.
    Erkennt externes EIN/AUS (z.B. direkt am myStrom-Taster) und
    startet/beendet Sessions automatisch.
    """
    from app.database import AsyncSessionLocal

    # {machine_id: letzter bekannter Zustand (True=on, False=off, None=unbekannt)}
    last_state: dict[int, bool | None] = {}
    # {machine_id: Zeitpunkt des letzten Polls}
    last_poll: dict[int, datetime] = {}

    while True:
        await asyncio.sleep(10)  # Prüf-Loop alle 10s — entscheidet pro Maschine ob Poll fällig
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Machine).where(
                        Machine.status == "online",
                        Machine.plug_type != "none",
                        Machine.plug_ip != None,
                    )
                )
                machines = result.scalars().all()

                now = datetime.utcnow()
                for m in machines:
                    interval_sec = m.plug_poll_interval_sec or 60
                    last = last_poll.get(m.id)
                    if last and (now - last).total_seconds() < interval_sec:
                        continue  # noch nicht fällig

                    last_poll[m.id] = now
                    status = await get_plug_status(m)
                    plug_on = status.get("on")

                    if plug_on is None:
                        continue  # Plug nicht erreichbar

                    prev = last_state.get(m.id)
                    last_state[m.id] = plug_on

                    if prev is None:
                        continue  # Erster Poll — nur Zustand merken, keine Aktion

                    if plug_on == prev:
                        continue  # Keine Änderung

                    # ── Zustand hat sich geändert ──────────────────
                    if plug_on and not m.session_started_at:
                        # Extern eingeschaltet → Manager-Session starten
                        # Ersten verfügbaren User als Session-Owner eintragen (FK-Constraint)
                        from app.models import User
                        user_res = await db.execute(select(User).order_by(User.id).limit(1))
                        fallback_user = user_res.scalars().first()
                        fallback_uid = fallback_user.id if fallback_user else None
                        log.info(f"Plug-Watcher: {m.name} extern EIN — starte Manager-Session (user_id={fallback_uid})")
                        await start_manager_session(db, m, user_id=fallback_uid)
                        await log_svc.log(
                            db, LogType.plug_on,
                            f"Extern eingeschaltet (Taster): {m.name}",
                            machine_id=m.id,
                            user_id=fallback_uid,
                        )
                        await log_svc.log(
                            db, LogType.session_started,
                            f"Session gestartet (Polling): {m.name}",
                            machine_id=m.id,
                            user_id=fallback_uid,
                        )

                    elif not plug_on and m.session_started_at:
                        # Extern ausgeschaltet → Session beenden
                        log.info(f"Plug-Watcher: {m.name} extern AUS — beende Session")
                        power = status.get("power_w")
                        energy_wh = None
                        if m.session_started_at and power is not None:
                            duration_h = (now - m.session_started_at).total_seconds() / 3600
                            energy_wh = power * duration_h
                        await end_session(db, m, ended_by=SessionEndedBy.system, energy_wh=energy_wh)
                        await log_svc.log(
                            db, LogType.plug_off,
                            f"Extern ausgeschaltet (Taster): {m.name}",
                            machine_id=m.id,
                        )

        except Exception as e:
            log.error(f"Plug-Watcher Fehler: {e}")
