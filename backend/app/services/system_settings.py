from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import SystemSettings


async def get_system_settings(db: AsyncSession) -> SystemSettings:
    result = await db.execute(select(SystemSettings).where(SystemSettings.id == 1))
    row = result.scalar_one_or_none()
    if not row:
        from app.config import get_settings
        env = get_settings()
        row = SystemSettings(
            id=1,
            nfc_writer_url=env.nfc_writer_url,
            jwt_expire_minutes=env.jwt_expire_minutes,
            guest_token_days=365,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row
