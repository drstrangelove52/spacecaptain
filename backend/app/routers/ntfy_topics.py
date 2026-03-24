from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models import NtfyTopic
from app.routers.auth import get_current_user
from app.services.auth import require_admin

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
    _=Depends(require_admin),
):
    t = NtfyTopic(**body.model_dump())
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _serialize(t)


@router.put("/{topic_id}")
async def update_topic(
    topic_id: int,
    body: NtfyTopicIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(NtfyTopic).where(NtfyTopic.id == topic_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Nicht gefunden")
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    await db.commit()
    await db.refresh(t)
    return _serialize(t)


@router.delete("/{topic_id}")
async def delete_topic(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(NtfyTopic).where(NtfyTopic.id == topic_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Nicht gefunden")
    await db.delete(t)
    await db.commit()
    return {"ok": True}
