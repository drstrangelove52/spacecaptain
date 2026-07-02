from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, LogType
from app.services.auth import require_admin, get_current_user
from app.services.system_settings import get_system_settings
from app.services.logger import log as activity_log

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsOut(BaseModel):
    nfc_writer_url: str
    jwt_expire_minutes: int
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
    emergency_plug_id: Optional[int] = None
    emergency_plug2_id: Optional[int] = None
    auto_backup_enabled: bool = False
    auto_backup_hour: int = 3
    auto_backup_minute: int = 0
    auto_backup_keep: int = 30
    space_name: str = ""
    room_open: bool = False
    room_open_since: Optional[datetime] = None
    room_open_auto: bool = True
    guest_token_ttl_hours: int = 8
    ts_enabled: bool = False
    ts_authkey: Optional[str] = None
    ts_hostname: str = "spacecaptain"
    mcp_enabled: bool = False
    mcp_api_token: Optional[str] = None
    mcp_user_id: Optional[int] = None

    class Config:
        from_attributes = True


class SettingsUpdate(BaseModel):
    nfc_writer_url: Optional[str] = None
    jwt_expire_minutes: Optional[int] = None
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
    emergency_plug_id: Optional[int] = None
    emergency_plug2_id: Optional[int] = None
    auto_backup_enabled: Optional[bool] = None
    auto_backup_hour: Optional[int] = None
    auto_backup_minute: Optional[int] = None
    auto_backup_keep: Optional[int] = None
    space_name: Optional[str] = None
    room_open_auto: Optional[bool] = None
    guest_token_ttl_hours: Optional[int] = None
    ts_enabled: Optional[bool] = None
    ts_authkey: Optional[str] = None
    ts_hostname: Optional[str] = None
    mcp_enabled: Optional[bool] = None
    mcp_user_id: Optional[int] = None


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
        "space_name": s.space_name or "",
        "room_open": s.room_open,
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
    current_user: User = Depends(require_admin),
):
    row = await get_system_settings(db)
    if payload.nfc_writer_url is not None:
        row.nfc_writer_url = payload.nfc_writer_url
    if payload.jwt_expire_minutes is not None:
        row.jwt_expire_minutes = max(5, payload.jwt_expire_minutes)
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
    if payload.emergency_plug_id is not None:
        row.emergency_plug_id = payload.emergency_plug_id or None
    if payload.emergency_plug2_id is not None:
        row.emergency_plug2_id = payload.emergency_plug2_id or None
    if payload.auto_backup_enabled is not None:
        row.auto_backup_enabled = payload.auto_backup_enabled
    if payload.auto_backup_hour is not None:
        row.auto_backup_hour = max(0, min(23, payload.auto_backup_hour))
    if payload.auto_backup_minute is not None:
        row.auto_backup_minute = max(0, min(59, payload.auto_backup_minute))
    if payload.auto_backup_keep is not None:
        row.auto_backup_keep = max(1, payload.auto_backup_keep)
    if payload.space_name is not None:
        row.space_name = payload.space_name.strip()
    if payload.room_open_auto is not None:
        row.room_open_auto = payload.room_open_auto
    if payload.guest_token_ttl_hours is not None:
        row.guest_token_ttl_hours = max(1, min(720, payload.guest_token_ttl_hours))
    if payload.ts_enabled is not None:
        row.ts_enabled = payload.ts_enabled
    if payload.ts_authkey is not None:
        row.ts_authkey = payload.ts_authkey or None
    if payload.ts_hostname is not None:
        row.ts_hostname = payload.ts_hostname.strip() or "spacecaptain"
    if payload.mcp_enabled is not None:
        row.mcp_enabled = payload.mcp_enabled
    if payload.mcp_user_id is not None:
        row.mcp_user_id = payload.mcp_user_id if payload.mcp_user_id > 0 else None
    await db.commit()
    await db.refresh(row)
    await activity_log(db, LogType.settings_changed,
                       "Systemeinstellungen geändert", user_id=current_user.id)
    return row


@router.post("/room")
async def set_room_status(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Öffnet oder schliesst den Raum manuell."""
    from app.services.room import open_room, close_room
    open_val = bool(payload.get("open", False))
    if open_val:
        await open_room(db, user_id=current_user.id)
    else:
        await close_room(db, user_id=current_user.id)
    return {"room_open": open_val}


@router.post("/mcp/regenerate-token", response_model=SettingsOut)
async def regenerate_mcp_token(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Generiert einen neuen MCP-API-Token und gibt die aktuellen Settings zurück."""
    import secrets
    row = await get_system_settings(db)
    row.mcp_api_token = secrets.token_urlsafe(32)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/room")
async def get_room_status(db: AsyncSession = Depends(get_db)):
    """Öffentlich: aktueller Raum-Öffnungsstatus."""
    from app.config import APP_TIMEZONE
    from datetime import timezone
    row = await get_system_settings(db)
    since_iso = None
    if row.room_open_since:
        since_iso = row.room_open_since.replace(tzinfo=timezone.utc).astimezone(APP_TIMEZONE).isoformat()
    return {"room_open": row.room_open, "room_open_since": since_iso, "room_open_auto": row.room_open_auto}
