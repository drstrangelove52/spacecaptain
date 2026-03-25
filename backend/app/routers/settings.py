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
    display_page_size: int = 8
    dashboard_refresh_seconds: int = 30
    ticker_text: Optional[str] = None
    ticker_speed: int = 80
    ticker_font_size: int = 18
    announcement: Optional[str] = None
    announcement_font_size: int = 20
    agb_text: Optional[str] = None
    ntfy_server: str = "https://ntfy.sh"
    ntfy_token: Optional[str] = None
    emergency_trigger_token: Optional[str] = None
    emergency_text: Optional[str] = None
    emergency_ntfy_message: Optional[str] = None
    emergency_duration_sec: int = 0
    emergency_ntfy_topic_id: Optional[int] = None
    emergency_plug_ip: Optional[str] = None
    emergency_plug_type: Optional[str] = None
    emergency_plug_token: Optional[str] = None
    emergency_plug2_ip: Optional[str] = None
    emergency_plug2_type: Optional[str] = None
    emergency_plug2_token: Optional[str] = None

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
    display_page_size: Optional[int] = None
    dashboard_refresh_seconds: Optional[int] = None
    ticker_text: Optional[str] = None
    ticker_speed: Optional[int] = None
    ticker_font_size: Optional[int] = None
    announcement: Optional[str] = None
    announcement_font_size: Optional[int] = None
    agb_text: Optional[str] = None
    ntfy_server: Optional[str] = None
    ntfy_token: Optional[str] = None
    emergency_trigger_token: Optional[str] = None
    emergency_text: Optional[str] = None
    emergency_ntfy_message: Optional[str] = None
    emergency_duration_sec: Optional[int] = None
    emergency_ntfy_topic_id: Optional[int] = None
    emergency_plug_ip: Optional[str] = None
    emergency_plug_type: Optional[str] = None
    emergency_plug_token: Optional[str] = None
    emergency_plug2_ip: Optional[str] = None
    emergency_plug2_type: Optional[str] = None
    emergency_plug2_token: Optional[str] = None


@router.get("/public")
async def read_settings_public(db: AsyncSession = Depends(get_db)):
    """Öffentliche Einstellungen (kein Auth) — nur für Display."""
    s = await get_system_settings(db)
    return {
        "display_refresh_seconds": s.display_refresh_seconds,
        "display_page_size": s.display_page_size,
        "ticker_text": s.ticker_text or "",
        "ticker_speed": s.ticker_speed,
        "ticker_font_size": s.ticker_font_size,
        "announcement": s.announcement or "",
        "announcement_font_size": s.announcement_font_size,
        "agb_text": s.agb_text or "",
    }


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
    if payload.display_page_size is not None:
        row.display_page_size = max(1, payload.display_page_size)
    if payload.dashboard_refresh_seconds is not None:
        row.dashboard_refresh_seconds = max(5, payload.dashboard_refresh_seconds)
    if payload.ticker_text is not None:
        row.ticker_text = payload.ticker_text or None
    if payload.ticker_speed is not None:
        row.ticker_speed = max(20, min(400, payload.ticker_speed))
    if payload.ticker_font_size is not None:
        row.ticker_font_size = max(10, min(72, payload.ticker_font_size))
    if payload.announcement is not None:
        row.announcement = payload.announcement or None
    if payload.announcement_font_size is not None:
        row.announcement_font_size = max(10, min(72, payload.announcement_font_size))
    if payload.agb_text is not None:
        row.agb_text = payload.agb_text or None
    if payload.ntfy_server is not None:
        row.ntfy_server = payload.ntfy_server or "https://ntfy.sh"
    if payload.ntfy_token is not None:
        row.ntfy_token = payload.ntfy_token or None
    if payload.emergency_trigger_token is not None:
        row.emergency_trigger_token = payload.emergency_trigger_token or None
    if payload.emergency_text is not None:
        row.emergency_text = payload.emergency_text or None
    if payload.emergency_ntfy_message is not None:
        row.emergency_ntfy_message = payload.emergency_ntfy_message or None
    if payload.emergency_duration_sec is not None:
        row.emergency_duration_sec = max(0, payload.emergency_duration_sec)
    if payload.emergency_ntfy_topic_id is not None:
        row.emergency_ntfy_topic_id = payload.emergency_ntfy_topic_id or None
    if payload.emergency_plug_ip is not None:
        row.emergency_plug_ip = payload.emergency_plug_ip or None
    if payload.emergency_plug_type is not None:
        row.emergency_plug_type = payload.emergency_plug_type or None
    if payload.emergency_plug_token is not None:
        row.emergency_plug_token = payload.emergency_plug_token or None
    if payload.emergency_plug2_ip is not None:
        row.emergency_plug2_ip = payload.emergency_plug2_ip or None
    if payload.emergency_plug2_type is not None:
        row.emergency_plug2_type = payload.emergency_plug2_type or None
    if payload.emergency_plug2_token is not None:
        row.emergency_plug2_token = payload.emergency_plug2_token or None
    await db.commit()
    await db.refresh(row)
    return row
