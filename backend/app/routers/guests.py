import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.database import get_db
import bcrypt

def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()
from app.models import User, Guest, Machine, Permission, LogType
from app.schemas import GuestCreate, GuestUpdate, GuestOut, GuestRegister
from app.services.auth import get_current_user
from app.services import logger as log_svc

router = APIRouter(prefix="/guests", tags=["guests"])


async def _guest_out(guest: Guest, db: AsyncSession) -> GuestOut:
    # Explizite Grants (Schulungs-Maschinen)
    granted = await db.execute(
        select(func.count()).where(Permission.guest_id == guest.id, Permission.is_blocked == False)
    )
    # Offene Maschinen gesamt
    open_total = await db.execute(
        select(func.count()).where(Machine.training_required == False)
    )
    # Explizit gesperrte Maschinen für diesen Gast
    blocked = await db.execute(
        select(func.count()).where(Permission.guest_id == guest.id, Permission.is_blocked == True)
    )
    count = (granted.scalar() or 0) + (open_total.scalar() or 0) - (blocked.scalar() or 0)
    out = GuestOut.model_validate(guest)
    out.permission_count = count
    return out


@router.get("", response_model=List[GuestOut])
async def list_guests(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Guest).where(Guest.pending_approval == False).order_by(Guest.created_at.desc())
    )
    guests = result.scalars().all()
    return [await _guest_out(g, db) for g in guests]


@router.get("/check-username")
async def check_username(u: str, db: AsyncSession = Depends(get_db)):
    """Öffentlich — prüft ob ein Benutzername verfügbar ist."""
    existing = await db.execute(select(Guest).where(Guest.username == u))
    taken = existing.scalar_one_or_none() is not None
    return {"available": not taken}


@router.get("/pending", response_model=List[GuestOut])
async def list_pending_guests(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Guest).where(Guest.pending_approval == True).order_by(Guest.created_at.asc())
    )
    guests = result.scalars().all()
    return [await _guest_out(g, db) for g in guests]


@router.post("/register")
async def register_guest(
    payload: GuestRegister,
    db: AsyncSession = Depends(get_db),
):
    """Öffentlicher Endpunkt — Gast-Selbstregistrierung (wartet auf Lab Manager Freigabe)."""
    existing = await db.execute(select(Guest).where(Guest.username == payload.username))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Benutzername bereits vergeben")
    if payload.email:
        ex_email = await db.execute(select(Guest).where(Guest.email == payload.email))
        if ex_email.scalar_one_or_none():
            raise HTTPException(400, "E-Mail-Adresse bereits registriert")
    guest = Guest(
        name=payload.name,
        username=payload.username,
        password_hash=_hash(payload.password),
        email=payload.email or None,
        phone=payload.phone or None,
        is_active=False,
        pending_approval=True,
        ntfy_topic=f"sc-{secrets.token_urlsafe(12)}",
    )
    db.add(guest)
    await db.commit()
    await db.refresh(guest)
    await log_svc.log(db, LogType.guest_registered, f"Gast {guest.name} hat sich selbst registriert", guest_id=guest.id)
    return {"ok": True, "message": "Registrierung eingegangen. Ein Lab Manager schaltet deinen Zugang frei."}


@router.post("/{guest_id}/approve", response_model=GuestOut)
async def approve_guest(
    guest_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    result = await db.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")
    guest.is_active = True
    guest.pending_approval = False
    await db.commit()
    await db.refresh(guest)
    await log_svc.log(db, LogType.guest_approved, f"Gast {guest.name} freigeschaltet", guest_id=guest.id, user_id=current.id)
    return await _guest_out(guest, db)


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
    data['ntfy_topic'] = f"sc-{secrets.token_urlsafe(12)}"
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


@router.post("/{guest_id}/ntfy-test")
async def send_guest_ntfy_test(
    guest_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Sendet eine Test-Benachrichtigung an das persönliche ntfy-Topic des Gastes."""
    result = await db.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")
    if not guest.ntfy_topic:
        raise HTTPException(400, "Kein ntfy-Topic für diesen Gast vorhanden")

    from app.models import SystemSettings
    from app.services.ntfy import send_notification
    cfg = await db.get(SystemSettings, 1)
    ok = await send_notification(
        server=cfg.ntfy_server if cfg and cfg.ntfy_server else "https://ntfy.sh",
        token=cfg.ntfy_token if cfg else None,
        topic=guest.ntfy_topic,
        title="SpaceCaptain — Testbenachrichtigung",
        message=f"Hallo {guest.name}! Deine ntfy-Benachrichtigungen für SpaceCaptain funktionieren.",
        priority="default",
    )
    if not ok:
        raise HTTPException(500, "ntfy-Benachrichtigung konnte nicht gesendet werden")
    return {"ok": True}
