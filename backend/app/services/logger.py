from sqlalchemy.ext.asyncio import AsyncSession
from app.models import ActivityLog, LogType


async def log(
    db: AsyncSession,
    type: LogType,
    message: str,
    guest_id: int | None = None,
    machine_id: int | None = None,
    user_id: int | None = None,
    meta: dict | None = None,
):
    entry = ActivityLog(
        type=type,
        message=message,
        guest_id=guest_id,
        machine_id=machine_id,
        user_id=user_id,
        meta=meta,
    )
    db.add(entry)
    await db.commit()
