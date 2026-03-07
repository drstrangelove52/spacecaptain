"""
Wartelisten-Service: Verwaltet die Warteliste wenn eine Maschine frei wird.
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import MachineQueue, QueueStatus

log = logging.getLogger(__name__)


async def notify_next_in_queue(db: AsyncSession, machine_id: int, reservation_minutes: int) -> None:
    """Setzt den nächsten Gast in der Warteliste auf 'notified'."""
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
