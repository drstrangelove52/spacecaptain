from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date, time

from app.database import get_db
from app.models import Announcement, LogType
from app.routers.auth import get_current_user
from app.services.logger import log as activity_log
from app.config import APP_TIMEZONE

router = APIRouter(prefix="/announcements", tags=["announcements"])

DAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


# ── Schemas ────────────────────────────────────────────────────────────────────

class AnnouncementIn(BaseModel):
    text: str
    is_active: bool = True
    is_recurring: bool = False
    display_type: str = "banner"            # "banner" | "ticker"
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    recur_days: Optional[str] = None        # "0,1,2,3,4"
    recur_start_time: Optional[time] = None
    recur_end_time: Optional[time] = None
    recur_valid_from: Optional[date] = None
    recur_valid_until: Optional[date] = None


def _is_currently_active(ann: Announcement) -> bool:
    """Berechnet ob eine Mitteilung zum aktuellen Zeitpunkt angezeigt werden soll."""
    if not ann.is_active:
        return False
    now = datetime.now(APP_TIMEZONE)

    if ann.is_recurring:
        if ann.recur_valid_from and now.date() < ann.recur_valid_from:
            return False
        if ann.recur_valid_until and now.date() > ann.recur_valid_until:
            return False
        if ann.recur_days:
            allowed = [int(d) for d in ann.recur_days.split(",") if d.strip().isdigit()]
            if now.weekday() not in allowed:
                return False
        current_time = now.time().replace(tzinfo=None)
        if ann.recur_start_time and current_time < ann.recur_start_time:
            return False
        if ann.recur_end_time and current_time > ann.recur_end_time:
            return False
        return True
    else:
        # einmalig: kein start_at = sofort aktiv; kein end_at = dauerhaft
        now_naive = now.replace(tzinfo=None)
        if ann.start_at and now_naive < ann.start_at:
            return False
        if ann.end_at and now_naive > ann.end_at:
            return False
        return True


def _status_label(ann: Announcement) -> str:
    if not ann.is_active:
        return "deaktiviert"
    now = datetime.now(APP_TIMEZONE).replace(tzinfo=None)
    if ann.is_recurring:
        if ann.recur_valid_until and now.date() > ann.recur_valid_until:
            return "abgelaufen"
        if _is_currently_active(ann):
            return "aktiv"
        return "geplant"
    else:
        if ann.end_at and now > ann.end_at:
            return "abgelaufen"
        if ann.start_at and now < ann.start_at:
            return "geplant"
        return "aktiv"


def _serialize(ann: Announcement) -> dict:
    return {
        "id": ann.id,
        "text": ann.text,
        "is_active": ann.is_active,
        "is_recurring": ann.is_recurring,
        "display_type": ann.display_type or "banner",
        "start_at": ann.start_at.isoformat() if ann.start_at else None,
        "end_at": ann.end_at.isoformat() if ann.end_at else None,
        "recur_days": ann.recur_days,
        "recur_start_time": ann.recur_start_time.strftime("%H:%M") if ann.recur_start_time else None,
        "recur_end_time": ann.recur_end_time.strftime("%H:%M") if ann.recur_end_time else None,
        "recur_valid_from": ann.recur_valid_from.isoformat() if ann.recur_valid_from else None,
        "recur_valid_until": ann.recur_valid_until.isoformat() if ann.recur_valid_until else None,
        "created_at": ann.created_at.isoformat(),
        "status": _status_label(ann),
        "currently_active": _is_currently_active(ann),
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("")
async def list_announcements(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(select(Announcement).order_by(Announcement.created_at.desc()))
    return [_serialize(a) for a in result.scalars().all()]


@router.get("/active")
async def active_announcements(db: AsyncSession = Depends(get_db)):
    """Öffentlicher Endpunkt — keine Authentifizierung nötig."""
    result = await db.execute(select(Announcement).where(Announcement.is_active == True))
    active = [a for a in result.scalars().all() if _is_currently_active(a)]
    return [{"id": a.id, "text": a.text, "display_type": a.display_type or "banner"} for a in active]


@router.post("")
async def create_announcement(
    body: AnnouncementIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ann = Announcement(**body.model_dump())
    db.add(ann)
    await db.commit()
    await db.refresh(ann)
    await activity_log(db, LogType.announcement_created,
                       f"Mitteilung erstellt: «{ann.text[:60]}»", user_id=current_user.id)
    return _serialize(ann)


@router.put("/{ann_id}")
async def update_announcement(
    ann_id: int,
    body: AnnouncementIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(select(Announcement).where(Announcement.id == ann_id))
    ann = result.scalar_one_or_none()
    if not ann:
        raise HTTPException(404, "Nicht gefunden")
    for k, v in body.model_dump().items():
        setattr(ann, k, v)
    await db.commit()
    await db.refresh(ann)
    await activity_log(db, LogType.announcement_updated,
                       f"Mitteilung aktualisiert: «{ann.text[:60]}»", user_id=current_user.id)
    return _serialize(ann)


@router.delete("/{ann_id}")
async def delete_announcement(
    ann_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(select(Announcement).where(Announcement.id == ann_id))
    ann = result.scalar_one_or_none()
    if not ann:
        raise HTTPException(404, "Nicht gefunden")
    text_preview = ann.text[:60]
    await db.delete(ann)
    await db.commit()
    await activity_log(db, LogType.announcement_deleted,
                       f"Mitteilung gelöscht: «{text_preview}»", user_id=current_user.id)
    return {"ok": True}
