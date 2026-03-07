from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services.auth import require_admin
from app.services.system_settings import get_system_settings

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsOut(BaseModel):
    nfc_writer_url: str
    jwt_expire_minutes: int
    guest_token_days: int
    modal_backdrop_input: bool
    modal_backdrop_display: bool
    queue_reservation_minutes: int
    display_refresh_seconds: int

    class Config:
        from_attributes = True


class SettingsUpdate(BaseModel):
    nfc_writer_url: Optional[str] = None
    jwt_expire_minutes: Optional[int] = None
    guest_token_days: Optional[int] = None
    modal_backdrop_input: Optional[bool] = None
    modal_backdrop_display: Optional[bool] = None
    queue_reservation_minutes: Optional[int] = None
    display_refresh_seconds: Optional[int] = None


@router.get("/public")
async def read_settings_public(db: AsyncSession = Depends(get_db)):
    """Öffentliche Einstellungen (kein Auth) — nur für Display."""
    s = await get_system_settings(db)
    return {"display_refresh_seconds": s.display_refresh_seconds}


@router.get("", response_model=SettingsOut)
async def read_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    return await get_system_settings(db)


@router.patch("", response_model=SettingsOut)
async def update_settings(
    payload: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await get_system_settings(db)
    if payload.nfc_writer_url is not None:
        row.nfc_writer_url = payload.nfc_writer_url
    if payload.jwt_expire_minutes is not None:
        row.jwt_expire_minutes = max(5, payload.jwt_expire_minutes)
    if payload.guest_token_days is not None:
        row.guest_token_days = max(1, payload.guest_token_days)
    if payload.modal_backdrop_input is not None:
        row.modal_backdrop_input = payload.modal_backdrop_input
    if payload.modal_backdrop_display is not None:
        row.modal_backdrop_display = payload.modal_backdrop_display
    if payload.queue_reservation_minutes is not None:
        row.queue_reservation_minutes = max(1, payload.queue_reservation_minutes)
    if payload.display_refresh_seconds is not None:
        row.display_refresh_seconds = max(10, payload.display_refresh_seconds)
    await db.commit()
    await db.refresh(row)
    return row
