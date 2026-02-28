import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.database import get_db
import bcrypt

def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()
from app.models import User, Guest, Permission, LogType
from app.schemas import GuestCreate, GuestUpdate, GuestOut
from app.services.auth import get_current_user
from app.services import logger as log_svc

router = APIRouter(prefix="/guests", tags=["guests"])


async def _guest_out(guest: Guest, db: AsyncSession) -> GuestOut:
    perm_count = await db.execute(
        select(func.count()).where(Permission.guest_id == guest.id)
    )
    count = perm_count.scalar() or 0
    out = GuestOut.model_validate(guest)
    out.permission_count = count
    return out


@router.get("", response_model=List[GuestOut])
async def list_guests(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Guest).order_by(Guest.created_at.desc()))
    guests = result.scalars().all()
    return [await _guest_out(g, db) for g in guests]


@router.post("", response_model=GuestOut)
async def create_guest(
    payload: GuestCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # Username-Konflikt prüfen
    existing = await db.execute(select(Guest).where(Guest.username == payload.username))
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Benutzername '{payload.username}' bereits vergeben")

    data = payload.model_dump(exclude={'password'})
    # Leere Strings → None (verhindert UNIQUE-Konflikt bei email/phone)
    for field in ('email', 'phone', 'note'):
        if field in data and data[field] == '':
            data[field] = None
    data['password_hash'] = _hash(payload.password)
    guest = Guest(**data)
    db.add(guest)
    await db.commit()
    await db.refresh(guest)
    await log_svc.log(db, LogType.guest_created, f"Gast {guest.name} registriert", guest_id=guest.id, user_id=current.id)
    return await _guest_out(guest, db)


@router.get("/{guest_id}", response_model=GuestOut)
async def get_guest(
    guest_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")
    return await _guest_out(guest, db)


@router.patch("/{guest_id}", response_model=GuestOut)
async def update_guest(
    guest_id: int,
    payload: GuestUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    result = await db.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")
    update_data = payload.model_dump(exclude_unset=True, exclude={'password'})
    # Username-Konflikt prüfen
    if 'username' in update_data and update_data['username'] != guest.username:
        existing = await db.execute(select(Guest).where(Guest.username == update_data['username']))
        if existing.scalar_one_or_none():
            raise HTTPException(400, f"Benutzername bereits vergeben")
    # Leere Strings → None
    for field in ('email', 'phone', 'note'):
        if field in update_data and update_data[field] == '':
            update_data[field] = None
    for field, value in update_data.items():
        setattr(guest, field, value)
    if payload.password:
        guest.password_hash = _hash(payload.password)
    await db.commit()
    await db.refresh(guest)
    return await _guest_out(guest, db)


@router.delete("/{guest_id}")
async def delete_guest(
    guest_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    result = await db.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Nicht gefunden")
    await log_svc.log(db, LogType.guest_deleted, f"Gast {guest.name} gelöscht", user_id=current.id)
    await db.delete(guest)
    await db.commit()
    return {"ok": True}


# ── Berechtigungen eines Gastes ────────────────────────────────────────────────
@router.get("/{guest_id}/permissions")
async def guest_permissions(
    guest_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Permission).where(Permission.guest_id == guest_id)
    )
    perms = result.scalars().all()
    return [{"machine_id": p.machine_id, "granted_at": p.granted_at} for p in perms]


# ── Login-Token generieren/zurücksetzen ───────────────
@router.post("/{guest_id}/login-token")
async def generate_login_token(
    guest_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Generiert einen neuen persönlichen Login-Token für den Gast."""
    result = await db.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")
    guest.login_token = secrets.token_urlsafe(32)
    await db.commit()
    await db.refresh(guest)
    return {"login_token": guest.login_token}


@router.delete("/{guest_id}/login-token")
async def revoke_login_token(
    guest_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Widerruft den Login-Token — Gast muss wieder mit Passwort einloggen."""
    result = await db.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")
    guest.login_token = None
    await db.commit()
    return {"ok": True}
