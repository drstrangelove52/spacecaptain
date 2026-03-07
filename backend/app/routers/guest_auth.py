"""
Gäste-Authentifizierung & Maschinenzugang
"""
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from jose import JWTError, jwt
import bcrypt
import logging
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models import Guest, Machine, Permission, LogType, ActivityLog, User
from app.config import get_settings
from app.services import logger as log_svc
from app.config import APP_TIMEZONE

def _local_iso(dt):
    if dt is None: return None
    from datetime import timezone
    return dt.replace(tzinfo=timezone.utc).astimezone(APP_TIMEZONE).isoformat()
from app.services.plug import switch_plug, get_plug_status
from app.services.session import start_session, end_session
from app.models import SessionEndedBy

router = APIRouter(prefix="/guest", tags=["guest"])
settings = get_settings()
log = logging.getLogger(__name__)


def create_guest_token(guest_id: int) -> str:
    expire = datetime.utcnow() + timedelta(hours=8)
    return jwt.encode(
        {"sub": str(guest_id), "type": "guest", "exp": expire},
        settings.jwt_secret, algorithm=settings.jwt_algorithm
    )

async def get_current_guest(token: str, db: AsyncSession) -> Guest:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "guest":
            raise ValueError("wrong token type")
        guest_id = int(payload["sub"])
    except (JWTError, TypeError, ValueError) as e:
        raise HTTPException(401, "Ungültiger oder abgelaufener Token")
    result = await db.execute(select(Guest).where(Guest.id == guest_id, Guest.is_active == True))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(401, "Gast nicht gefunden oder inaktiv")
    return guest


class GuestLoginRequest(BaseModel):
    username: str
    password: str

class SwitchRequest(BaseModel):
    access_token: str
    machine_token: str
    action: str

class CheckRequest(BaseModel):
    access_token: str
    machine_token: str


async def _machine_detail(machine: Machine) -> dict:
    from app.services.session import idle_since_global
    plug_state = await get_plug_status(machine)
    power_w = plug_state.get("power_w")

    # Leerlauf-Status berechnen
    idle_state = None
    idle_since_min = None
    if (machine.current_guest_id and machine.idle_power_w is not None
            and machine.idle_timeout_min is not None and power_w is not None):
        if power_w <= machine.idle_power_w:
            if machine.id in idle_since_global:
                idle_since_min = round(
                    (datetime.utcnow() - idle_since_global[machine.id]).total_seconds() / 60, 1
                )
                idle_state = 'idle_warning' if (machine.idle_timeout_min - idle_since_min) <= 2 else 'idle'
            else:
                idle_state = 'idle'
        else:
            idle_state = 'active'

    return {
        "id":              machine.id,
        "name":            machine.name,
        "category":        machine.category,
        "location":        machine.location or "—",
        "status":          machine.status,
        "comment":         machine.comment,
        "plug_type":       machine.plug_type,
        "plug_on":         plug_state.get("on"),
        "plug_supported":  plug_state.get("supported", False),
        "power_w":         power_w,
        "current_guest_id":   machine.current_guest_id,
        "session_manager_id": machine.session_manager_id,
        "session_started_at": _local_iso(machine.session_started_at),
        "idle_state":         idle_state,
        "idle_since_min":     idle_since_min,
        "idle_timeout_min":   machine.idle_timeout_min,
    }


# ── Login ─────────────────────────────────────────────
@router.post("/login")
async def guest_login(payload: GuestLoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Guest).where(Guest.username == payload.username, Guest.is_active == True)
    )
    guest = result.scalar_one_or_none()
    if not guest or not guest.password_hash:
        raise HTTPException(401, "Ungültiger Benutzername oder Passwort")
    if not bcrypt.checkpw(payload.password.encode(), guest.password_hash.encode()):
        raise HTTPException(401, "Ungültiger Benutzername oder Passwort")

    token = create_guest_token(guest.id)
    await log_svc.log(db, LogType.guest_login, f"Gast-Login: {guest.name} (@{guest.username})", guest_id=guest.id)
    return {
        "access_token": token, "token_type": "bearer",
        "guest_id": guest.id, "guest_name": guest.name, "username": guest.username,
    }


# ── Token-Link Login ──────────────────────────────────
class LoginByTokenRequest(BaseModel):
    login_token: str

@router.post("/login-by-token")
async def guest_login_by_token(
    payload: LoginByTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Gast-Login per persönlichem Token-Link — kein Passwort nötig."""
    result = await db.execute(
        select(Guest).where(Guest.login_token == payload.login_token, Guest.is_active == True)
    )
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(401, "Ungültiger oder abgelaufener Token-Link")

    token = create_guest_token(guest.id)
    await log_svc.log(db, LogType.guest_login,
        f"Gast-Login per Token-Link: {guest.name} (@{guest.username})", guest_id=guest.id)
    return {
        "access_token": token, "token_type": "bearer",
        "guest_id": guest.id, "guest_name": guest.name, "username": guest.username,
    }


# ── Maschineninfo (öffentlich) ────────────────────────
@router.get("/machine/{machine_token}")
async def machine_info(machine_token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Machine).where(Machine.qr_token == machine_token))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    detail = await _machine_detail(machine)
    if machine.current_guest_id:
        g = await db.get(Guest, machine.current_guest_id)
        detail["current_guest_name"] = g.name if g else None
    else:
        detail["current_guest_name"] = None

    # Laufzeit berechnen
    if machine.session_started_at:
        detail["session_duration_min"] = round(
            (datetime.utcnow() - machine.session_started_at).total_seconds() / 60, 1
        )
    else:
        detail["session_duration_min"] = None
    return detail


# ── Berechtigung prüfen ───────────────────────────────
@router.post("/check")
async def check_access(payload: CheckRequest, db: AsyncSession = Depends(get_db)):
    guest = await get_current_guest(payload.access_token, db)
    result = await db.execute(select(Machine).where(Machine.qr_token == payload.machine_token))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    perm_res = await db.execute(
        select(Permission).where(Permission.guest_id == guest.id, Permission.machine_id == machine.id)
    )
    perm = perm_res.scalar_one_or_none()
    if machine.training_required:
        has_permission = perm is not None and not perm.is_blocked
    else:
        has_permission = perm is None or not perm.is_blocked

    detail = await _machine_detail(machine)

    if machine.current_guest_id:
        g = await db.get(Guest, machine.current_guest_id)
        detail["current_guest_name"] = g.name if g else None
    else:
        detail["current_guest_name"] = None

    if machine.session_started_at:
        detail["session_duration_min"] = round(
            (datetime.utcnow() - machine.session_started_at).total_seconds() / 60, 1
        )

    # is_my_session: diese Maschine gehört dem anfragenden Gast
    detail["is_my_session"] = (machine.current_guest_id == guest.id) if machine.current_guest_id else False

    # Begründung des letzten Entzugs anzeigen (wenn keine Berechtigung)
    denial_reason = None
    if not has_permission:
        log_res = await db.execute(
            select(ActivityLog)
            .where(
                ActivityLog.guest_id == guest.id,
                ActivityLog.machine_id == machine.id,
                ActivityLog.type == LogType.permission_revoked,
            )
            .order_by(ActivityLog.created_at.desc())
            .limit(1)
        )
        log_entry = log_res.scalar_one_or_none()
        if log_entry and log_entry.meta and log_entry.meta.get("comment"):
            denial_reason = log_entry.meta["comment"]

    return {"guest_name": guest.name, "guest_id": guest.id, "has_permission": has_permission,
            "denial_reason": denial_reason, "machine": detail}


# ── Schalten ──────────────────────────────────────────
@router.post("/switch")
async def guest_switch(payload: SwitchRequest, db: AsyncSession = Depends(get_db)):
    guest = await get_current_guest(payload.access_token, db)

    # Machine IMMER frisch aus DB lesen (kein Cache)
    row = await db.execute(
        text("SELECT * FROM machines WHERE qr_token = :t"), {"t": payload.machine_token}
    )
    raw = row.mappings().one_or_none()
    if not raw:
        raise HTTPException(404, "Maschine nicht gefunden")

    result = await db.execute(select(Machine).where(Machine.qr_token == payload.machine_token))
    machine = result.scalar_one_or_none()

    current_guest_id_db = raw["current_guest_id"]  # direkt aus SQL, kein ORM-Cache
    log.info(f"switch: guest={guest.id}, machine={machine.id}, current_guest_id_db={current_guest_id_db}, action={payload.action}")

    if machine.status != "online":
        raise HTTPException(503, f"Maschine '{machine.name}' nicht verfügbar")

    perm_res = await db.execute(
        select(Permission).where(Permission.guest_id == guest.id, Permission.machine_id == machine.id)
    )
    perm_row = perm_res.scalar_one_or_none()
    if machine.training_required:
        has_access = perm_row is not None and not perm_row.is_blocked
    else:
        has_access = perm_row is None or not perm_row.is_blocked
    if not has_access:
        await log_svc.log(db, LogType.access_denied,
            f"Zugang verweigert: {guest.name} → {machine.name}",
            guest_id=guest.id, machine_id=machine.id)
        raise HTTPException(403, "Keine Berechtigung für diese Maschine")

    if payload.action not in ("on", "off"):
        raise HTTPException(400, "action muss 'on' oder 'off' sein")

    # AUS: Sperr-Logik
    if payload.action == "off":
        # Manager-Session (explizit gesetzt) → Gast darf nie ausschalten
        manager_id_db = raw.get("session_manager_id")
        if manager_id_db is not None:
            raise HTTPException(403, "Diese Maschine läuft in einer Manager-Session")
        # Maschine läuft, aber current_guest_id gehört nicht diesem Gast
        # (deckt auch gepollte Sessions ab, bei denen current_guest_id=NULL ist)
        if current_guest_id_db is None and raw.get("session_started_at") is not None:
            raise HTTPException(403, "Diese Maschine läuft in einer Manager-Session")
        # Fremde Gast-Session
        if current_guest_id_db is not None and int(current_guest_id_db) != int(guest.id):
            raise HTTPException(403, "Diese Maschine läuft in einer fremden Session")

    # Energie VOR dem Ausschalten messen (danach liefert der Plug 0W)
    energy_wh = None
    if payload.action == "off" and machine.session_started_at:
        plug_status = await get_plug_status(machine)
        if plug_status.get("power_w") is not None and plug_status["power_w"] > 0:
            duration_h = (datetime.utcnow() - machine.session_started_at).total_seconds() / 3600
            energy_wh = round(plug_status["power_w"] * duration_h, 3)

    ok, msg = await switch_plug(machine, payload.action)
    log_type = LogType.plug_on if payload.action == "on" else LogType.plug_off

    if ok:
        if payload.action == "on":
            await start_session(db, machine, guest.id)
            await log_svc.log(db, LogType.access_granted,
                f"Zugang: {guest.name} → {machine.name}", guest_id=guest.id, machine_id=machine.id)
        else:
            await end_session(db, machine, ended_by=SessionEndedBy.guest, energy_wh=energy_wh)

    await log_svc.log(db, log_type if ok else LogType.error,
        f"{'EIN' if payload.action == 'on' else 'AUS'}: {guest.name} → {machine.name} — {msg}",
        guest_id=guest.id, machine_id=machine.id)

    return {"ok": ok, "action": payload.action, "machine": machine.name, "message": msg}


# ── Gäste-Dashboard (öffentlich) ──────────────────────
@router.get("/dashboard")
async def guest_dashboard(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Machine).order_by(Machine.name))
    machines = result.scalars().all()

    out = []
    for m in machines:
        plug_state = await get_plug_status(m)
        current_guest_name = None
        if m.current_guest_id:
            g = await db.get(Guest, m.current_guest_id)
            current_guest_name = g.name if g else None

        session_duration_min = None
        if m.session_started_at:
            session_duration_min = round(
                (datetime.utcnow() - m.session_started_at).total_seconds() / 60, 1
            )

        out.append({
            "id":                   m.id,
            "name":                 m.name,
            "category":             m.category,
            "location":             m.location or "—",
            "status":               m.status,
            "comment":              m.comment,
            "plug_on":              plug_state.get("on"),
            "plug_supported":       plug_state.get("supported", False),
            "plug_error":           plug_state.get("error"),
            "power_w":              plug_state.get("power_w"),
            "in_use":               m.current_guest_id is not None,
            "current_guest_name":   current_guest_name,
            "session_duration_min": session_duration_min,
            "session_started_at":   _local_iso(m.session_started_at),
        })
    return out


# ── Passwort ändern ───────────────────────────────────
class ChangePasswordRequest(BaseModel):
    access_token: str
    current_password: str
    new_password: str

@router.post("/change-password")
async def change_password(payload: ChangePasswordRequest, db: AsyncSession = Depends(get_db)):
    guest = await get_current_guest(payload.access_token, db)

    # Altes Passwort prüfen
    if not bcrypt.checkpw(payload.current_password.encode(), guest.password_hash.encode()):
        raise HTTPException(400, "Aktuelles Passwort ist falsch")

    # Mindestlänge
    if len(payload.new_password) < 6:
        raise HTTPException(400, "Neues Passwort muss mindestens 6 Zeichen haben")

    guest.password_hash = bcrypt.hashpw(payload.new_password.encode(), bcrypt.gensalt(12)).decode()
    await db.commit()
    await log_svc.log(db, LogType.login, f"Passwort geändert: {guest.name}", guest_id=guest.id)
    return {"ok": True, "message": "Passwort erfolgreich geändert"}


# ── Statistiken ────────────────────────────────────────
@router.get("/stats/sessions")
async def session_stats(
    machine_id: Optional[int] = None,
    guest_id:   Optional[int] = None,
    days:       int = 30,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import and_
    from app.models import MachineSession
    since = datetime.utcnow() - timedelta(days=days)

    filters = [MachineSession.started_at >= since]
    if machine_id: filters.append(MachineSession.machine_id == machine_id)
    if guest_id:   filters.append(MachineSession.guest_id == guest_id)

    result = await db.execute(
        select(MachineSession).where(and_(*filters)).order_by(MachineSession.started_at.desc())
    )
    sessions = result.scalars().all()
    guests   = {g.id: g.name for g in (await db.execute(select(Guest))).scalars().all()}
    machines = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}
    users    = {u.id: u.name for u in (await db.execute(select(User))).scalars().all()}

    total_duration = sum(s.duration_min or 0 for s in sessions)
    total_energy   = sum(s.energy_wh or 0 for s in sessions)

    return {
        "summary": {
            "sessions":         len(sessions),
            "total_duration_h": round(total_duration / 60, 2),
            "total_energy_wh":  round(total_energy, 2),
            "total_energy_kwh": round(total_energy / 1000, 3),
        },
        "sessions": [{
            "id":           s.id,
            "machine_id":   s.machine_id,
            "machine_name": machines.get(s.machine_id, "?"),
            "guest_id":     s.guest_id,
            "guest_name":   guests.get(s.guest_id, "?") if s.guest_id else None,
            "manager_id":   s.manager_id,
            "user_name":    guests.get(s.guest_id) if s.guest_id else users.get(s.manager_id),
            "started_at":   _local_iso(s.started_at),
            "ended_at":     _local_iso(s.ended_at),
            "duration_min": s.duration_min,
            "energy_wh":    s.energy_wh,
            "ended_by":     s.ended_by,
        } for s in sessions]
    }
