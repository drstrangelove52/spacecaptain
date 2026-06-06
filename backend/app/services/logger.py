from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import ActivityLog, LogType, User


async def log(
    db: AsyncSession,
    type: LogType,
    message: str,
    guest_id: int | None = None,
    machine_id: int | None = None,
    user_id: int | None = None,
    meta: dict | None = None,
):
    resolved_meta = dict(meta) if meta else {}
    if user_id and "user_name" not in resolved_meta:
        user = await db.scalar(select(User).where(User.id == user_id))
        if user:
            resolved_meta["user_name"] = user.name
    entry = ActivityLog(
        type=type,
        message=message,
        guest_id=guest_id,
        machine_id=machine_id,
        user_id=user_id,
        meta=resolved_meta if resolved_meta else None,
    )
    db.add(entry)
    await db.commit()
