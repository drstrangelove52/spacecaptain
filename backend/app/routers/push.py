"""
Push-Notification Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_db
from app.models import PushSubscription
from app.config import get_settings

router = APIRouter(prefix="/push", tags=["push"])


class SubscribePayload(BaseModel):
    access_token: str
    endpoint: str
    p256dh: str
    auth: str


@router.get("/vapid-key")
async def get_vapid_key():
    """Gibt den öffentlichen VAPID-Schlüssel zurück."""
    settings = get_settings()
    return {"public_key": settings.vapid_public_key}


@router.post("/subscribe")
async def subscribe(payload: SubscribePayload, db: AsyncSession = Depends(get_db)):
    """Speichert eine Push-Subscription für einen Gast."""
    from app.services.auth import decode_guest_token
    token_data = decode_guest_token(payload.access_token)
    if not token_data:
        raise HTTPException(401, "Ungültiger Token")
    guest_id = token_data.get("guest_id")

    # Upsert: bestehende Subscription für diesen Gast + Endpoint aktualisieren
    existing = await db.execute(
        select(PushSubscription).where(
            PushSubscription.guest_id == guest_id,
            PushSubscription.endpoint == payload.endpoint,
        )
    )
    sub = existing.scalar_one_or_none()
    if sub:
        sub.p256dh = payload.p256dh
        sub.auth = payload.auth
    else:
        sub = PushSubscription(
            guest_id=guest_id,
            endpoint=payload.endpoint,
            p256dh=payload.p256dh,
            auth=payload.auth,
        )
        db.add(sub)
    await db.commit()
    return {"ok": True}


@router.delete("/subscribe")
async def unsubscribe(access_token: str, endpoint: str, db: AsyncSession = Depends(get_db)):
    """Löscht eine Push-Subscription."""
    from app.services.auth import decode_guest_token
    token_data = decode_guest_token(access_token)
    if not token_data:
        raise HTTPException(401, "Ungültiger Token")
    guest_id = token_data.get("guest_id")

    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.guest_id == guest_id,
            PushSubscription.endpoint == endpoint,
        )
    )
    await db.commit()
    return {"ok": True}
