from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models import NtfyTopic, SystemSettings, LogType
from app.routers.auth import get_current_user
from app.services.auth import require_admin
from app.services.ntfy import send_notification
from app.services.logger import log as activity_log

router = APIRouter(prefix="/ntfy-topics", tags=["ntfy"])


class NtfyTopicIn(BaseModel):
    key: str
    topic: str
    title: str
    description: Optional[str] = None


def _serialize(t: NtfyTopic) -> dict:
    return {
        "id": t.id,
        "key": t.key,
        "topic": t.topic,
        "title": t.title,
        "description": t.description,
        "created_at": t.created_at.isoformat(),
    }


@router.get("")
async def list_topics(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(select(NtfyTopic).order_by(NtfyTopic.title))
    return [_serialize(t) for t in result.scalars().all()]


@router.post("")
async def create_topic(
    body: NtfyTopicIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    t = NtfyTopic(**body.model_dump())
    db.add(t)
    await db.commit()
    await db.refresh(t)
    await activity_log(db, LogType.ntfy_topic_created,
                       f"ntfy-Topic erstellt: «{t.title}»", user_id=current_user.id)
    return _serialize(t)


@router.put("/{topic_id}")
async def update_topic(
    topic_id: int,
    body: NtfyTopicIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(select(NtfyTopic).where(NtfyTopic.id == topic_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Nicht gefunden")
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    await db.commit()
    await db.refresh(t)
    await activity_log(db, LogType.ntfy_topic_updated,
                       f"ntfy-Topic aktualisiert: «{t.title}»", user_id=current_user.id)
    return _serialize(t)


@router.post("/{topic_id}/test")
async def test_topic(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(select(NtfyTopic).where(NtfyTopic.id == topic_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Nicht gefunden")
    cfg = await db.get(SystemSettings, 1)
    server = (cfg.ntfy_server if cfg and cfg.ntfy_server else "https://ntfy.sh")
    token = cfg.ntfy_token if cfg else None
    ok = await send_notification(
        server=server,
        token=token,
        topic=t.topic,
        title="SpaceCaptain Test",
        message=f"Test-Benachrichtigung für Topic «{t.title}»",
        tags=["test_tube"],
    )
    if not ok:
        raise HTTPException(502, "Benachrichtigung konnte nicht gesendet werden")
    return {"ok": True}


@router.delete("/{topic_id}")
async def delete_topic(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(select(NtfyTopic).where(NtfyTopic.id == topic_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Nicht gefunden")
    title = t.title
    await db.delete(t)
    await db.commit()
    await activity_log(db, LogType.ntfy_topic_deleted,
                       f"ntfy-Topic gelöscht: «{title}»", user_id=current_user.id)
    return {"ok": True}
