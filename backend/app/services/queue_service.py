"""
Wartelisten-Service: Verwaltet die Warteliste wenn eine Maschine frei wird.
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.models import MachineQueue, QueueStatus, Guest, Machine, LogType

log = logging.getLogger(__name__)


async def notify_next_in_queue(db: AsyncSession, machine_id: int, reservation_minutes: int) -> None:
    """Setzt den nächsten Gast in der Warteliste auf 'notified' und schickt ntfy."""
    result = await db.execute(
        select(MachineQueue).where(
            MachineQueue.machine_id == machine_id,
            MachineQueue.status == QueueStatus.waiting,
        ).order_by(MachineQueue.joined_at.asc()).limit(1)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        return

    now = datetime.utcnow()
    entry.status = QueueStatus.notified
    entry.notified_at = now
    entry.expires_at = now + timedelta(minutes=reservation_minutes)
    await db.commit()
    log.info(f"Queue: Gast {entry.guest_id} ist dran für Maschine {machine_id}")

    # ntfy-Benachrichtigung an den Gast senden
    try:
        guest = await db.get(Guest, entry.guest_id)
        machine = await db.get(Machine, machine_id)
        if guest and guest.ntfy_topic and machine:
            from app.services.ntfy import send_notification
            from app.models import SystemSettings
            cfg = await db.get(SystemSettings, 1)
            await send_notification(
                server=cfg.ntfy_server or "https://ntfy.sh",
                token=cfg.ntfy_token or None,
                topic=guest.ntfy_topic,
                title="Du bist dran!",
                message=f"{machine.name} ist jetzt frei. Du hast {reservation_minutes} Minuten um die Maschine zu starten.",
                priority="high",
            )
    except Exception as e:
        log.warning(f"Queue: ntfy-Benachrichtigung fehlgeschlagen für Gast {entry.guest_id}: {e}")

    try:
        from app.services.logger import log as activity_log
        await activity_log(db, LogType.queue_notified,
                           f"Gast {entry.guest_id} benachrichtigt für Maschine {machine_id}",
                           guest_id=entry.guest_id, machine_id=machine_id)
    except Exception as e:
        log.warning(f"Queue: Aktivitätslog fehlgeschlagen: {e}")


async def expire_stale_notifications(db: AsyncSession, reservation_minutes: int) -> None:
    """Setzt abgelaufene 'notified'-Einträge auf 'expired' und rückt Nächsten vor."""
    now = datetime.utcnow()
    result = await db.execute(
        select(MachineQueue).where(
            MachineQueue.status == QueueStatus.notified,
            MachineQueue.expires_at <= now,
        )
    )
    expired = result.scalars().all()
    for entry in expired:
        entry.status = QueueStatus.expired
        log.info(f"Queue: Eintrag {entry.id} abgelaufen (Gast {entry.guest_id}, Maschine {entry.machine_id})")

    if expired:
        await db.commit()
        machine_ids = {e.machine_id for e in expired}
        for mid in machine_ids:
            await notify_next_in_queue(db, mid, reservation_minutes)

    # Abgeschlossene Einträge (done/expired) löschen
    await db.execute(
        delete(MachineQueue).where(
            MachineQueue.status.in_([QueueStatus.done, QueueStatus.expired])
        )
    )
    await db.commit()
