import secrets
import logging
import io
import base64
import qrcode
from datetime import datetime

log = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.database import get_db
from app.models import User, Machine, Permission, LogType
from app.schemas import MachineCreate, MachineUpdate, MachineOut
from app.services.auth import get_current_user
from app.services import logger as log_svc
from app.services.plug import get_plug_status, switch_plug
from app.config import APP_TIMEZONE

def _local_iso(dt):
    if dt is None: return None
    from datetime import timezone
    return dt.replace(tzinfo=timezone.utc).astimezone(APP_TIMEZONE).isoformat()
from app.services.session import idle_since_global
from app.services.session import start_session, end_session, start_manager_session
from app.models import Guest, MachineSession, SessionEndedBy

router = APIRouter(prefix="/machines", tags=["machines"])


def _gen_qr_token() -> str:
    return secrets.token_urlsafe(32)


async def _machine_out(machine: Machine, db: AsyncSession) -> MachineOut:
    count_res = await db.execute(
        select(func.count()).where(Permission.machine_id == machine.id)
    )
    out = MachineOut.model_validate(machine)
    out.user_count = count_res.scalar() or 0
    # Explizit setzen damit lazy-loading kein Problem macht
    out.current_guest_id   = machine.current_guest_id
    out.session_manager_id = machine.session_manager_id
    out.session_started_at = machine.session_started_at
    return out


@router.get("", response_model=List[MachineOut])
async def list_machines(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Machine).order_by(Machine.created_at.desc()))
    machines = result.scalars().all()
    return [await _machine_out(m, db) for m in machines]


@router.get("/live")
async def list_machines_live(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Gibt Maschinenlist mit aktiver Session-Info zurück (Gastnamen, Laufzeit, Plug-Status)."""
    result = await db.execute(select(Machine).order_by(Machine.created_at.desc()))
    machines = result.scalars().all()

    # Alle Gäste + Manager in einem Query laden
    guests_res = await db.execute(select(Guest))
    guest_map = {g.id: g.name for g in guests_res.scalars().all()}
    users_res = await db.execute(select(User))
    user_map = {u.id: u.name for u in users_res.scalars().all()}

    out = []
    for m in machines:
        try:
            count_res = await db.execute(select(func.count()).where(Permission.machine_id == m.id))
            user_count = count_res.scalar() or 0

            # Session-Info
            current_guest_name = guest_map.get(m.current_guest_id) if m.current_guest_id else None
            session_owner = None
            if m.current_guest_id:
                session_owner = current_guest_name
            elif m.session_manager_id:
                session_owner = user_map.get(m.session_manager_id, 'Unbekannt')
            session_duration_min = None
            if m.session_started_at:
                session_duration_min = round((datetime.utcnow() - m.session_started_at).total_seconds() / 60, 1)

            # Plug-Status (nur wenn konfiguriert)
            plug_info = {"on": None, "power_w": None, "supported": False}
            if m.plug_type != "none" and m.plug_ip:
                try:
                    plug_info = await get_plug_status(m)
                except Exception:
                    plug_info = {"on": None, "power_w": None, "supported": True, "error": "unreachable"}

            # Leerlauf-Status berechnen
            idle_state = None
            idle_since_min = None
            power_w = plug_info.get("power_w")
            session_age_sec = (
                (datetime.utcnow() - m.session_started_at).total_seconds()
                if m.session_started_at else 0
            )
            if (m.session_started_at and m.idle_power_w is not None
                    and m.idle_timeout_min is not None and power_w is not None
                    and session_age_sec >= 60):  # 60s Anlaufzeit nach Session-Start
                if power_w <= m.idle_power_w:
                    if m.id in idle_since_global:
                        idle_since_min = round(
                            (datetime.utcnow() - idle_since_global[m.id]).total_seconds() / 60, 1
                        )
                        remaining = m.idle_timeout_min - idle_since_min
                        idle_state = 'idle_warning' if remaining <= 2 else 'idle'
                    else:
                        idle_state = 'idle'
                else:
                    idle_state = 'active'

            out.append({
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "location": m.location,
                "status": m.status,
                "comment": m.comment,
                "plug_type": m.plug_type,
                "plug_ip": m.plug_ip,
                "plug_token": m.plug_token,
                "plug_poll_interval_sec": m.plug_poll_interval_sec,
                "qr_token": m.qr_token,
                "user_count": user_count,
                "idle_power_w": m.idle_power_w,
                "idle_timeout_min": m.idle_timeout_min,
                "training_required": m.training_required,
                # Session
                "in_use": m.session_started_at is not None,
                "current_guest_id": m.current_guest_id,
                "current_guest_name": session_owner or current_guest_name,
                "session_manager_id": m.session_manager_id,
                "session_started_at": _local_iso(m.session_started_at),
                "session_duration_min": session_duration_min,
                # Plug live
                "plug_on": plug_info.get("on"),
                "power_w": power_w,
                "plug_supported": plug_info.get("supported", False),
                "plug_error": plug_info.get("error"),
                # Leerlauf
                "idle_state": idle_state,
                "idle_since_min": idle_since_min,
            })
        except Exception as e:
            log.error(f"Live-Endpoint Fehler für Maschine {m.id}: {e}")
            # Nur Plug-Daten fehlen — Session-State aus DB korrekt zurückgeben
            out.append({
                "id": m.id, "name": m.name, "category": m.category,
                "location": m.location, "status": m.status,
                "comment": m.comment, "plug_type": m.plug_type,
                "qr_token": m.qr_token,
                "user_count": 0,
                "idle_power_w": m.idle_power_w,
                "idle_timeout_min": m.idle_timeout_min,
                "training_required": m.training_required,
                "in_use": m.session_started_at is not None,
                "current_guest_id": m.current_guest_id,
                "current_guest_name": None,
                "session_manager_id": m.session_manager_id,
                "session_started_at": _local_iso(m.session_started_at),
                "session_duration_min": None,
                "plug_on": None, "power_w": None,
                "plug_supported": True, "plug_error": "unreachable",
                "idle_state": None, "idle_since_min": None,
            })
    return out


@router.post("", response_model=MachineOut)
async def create_machine(
    payload: MachineCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    machine = Machine(**payload.model_dump(), qr_token=_gen_qr_token())
    db.add(machine)
    await db.commit()
    await db.refresh(machine)
    await log_svc.log(
        db, LogType.machine_created,
        f"Maschine {machine.name} ({machine.category}) hinzugefügt",
        machine_id=machine.id, user_id=current.id
    )
    return await _machine_out(machine, db)


@router.get("/{machine_id}", response_model=MachineOut)
async def get_machine(
    machine_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")
    return await _machine_out(machine, db)


@router.patch("/{machine_id}", response_model=MachineOut)
async def update_machine(
    machine_id: int,
    payload: MachineUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(machine, field, value)
    await db.commit()
    await db.refresh(machine)
    return await _machine_out(machine, db)


@router.delete("/{machine_id}")
async def delete_machine(
    machine_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Nicht gefunden")
    await log_svc.log(db, LogType.machine_deleted, f"Maschine {machine.name} gelöscht", user_id=current.id)
    await db.delete(machine)
    await db.commit()
    return {"ok": True}


@router.post("/{machine_id}/regenerate-qr", response_model=MachineOut)
async def regenerate_qr(
    machine_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Neuen QR-Token für die Maschine generieren (invalidiert alte QR-Codes)."""
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Nicht gefunden")
    machine.qr_token = _gen_qr_token()
    await db.commit()
    await db.refresh(machine)
    return await _machine_out(machine, db)


@router.get("/{machine_id}/qr.png")
async def get_qr_image(
    machine_id: int,
    request: Request,
    token: str = None,  # Query param fallback für <img> tags
    db: AsyncSession = Depends(get_db),
):
    # Auth: entweder Bearer Header oder ?token= Query-Param
    from app.services.auth import get_settings as _gs
    from jose import jwt as _jwt
    settings = _gs()
    auth_token = token
    if not auth_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            auth_token = auth_header[7:]
    if not auth_token:
        raise HTTPException(401, "Nicht authentifiziert")
    try:
        _jwt.decode(auth_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except Exception:
        raise HTTPException(401, "Ungültiger Token")

    """Gibt das QR-Code Bild als PNG zurück (zum Drucken)."""
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Nicht gefunden")

    # QR-Code enthält die vollständige Gäste-URL
    # Der Hostname wird aus dem Request-Header ermittelt
    base_url = str(request.base_url).rstrip("/")
    guest_url = f"{base_url}/?m={machine.qr_token}"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(guest_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="qr_{machine_id}.png"'},
    )


@router.get("/{machine_id}/plug-status")
async def plug_status(
    machine_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Nicht gefunden")
    status = await get_plug_status(machine)
    # Aktiven Gast hinzufügen
    current_guest_name = None
    if machine.current_guest_id:
        g = await db.get(Guest, machine.current_guest_id)
        current_guest_name = g.name if g else None
    session_duration_min = None
    if machine.session_started_at:
        session_duration_min = round((datetime.utcnow() - machine.session_started_at).total_seconds() / 60, 1)
    return {
        **status,
        "current_guest_name": current_guest_name,
        "current_guest_id": machine.current_guest_id,
        "session_started_at": _local_iso(machine.session_started_at),
        "session_duration_min": session_duration_min,
    }


@router.post("/{machine_id}/switch")
async def manager_switch(
    machine_id: int,
    action: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Manager kann Maschine direkt ein/ausschalten."""
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Nicht gefunden")
    if action not in ("on", "off"):
        raise HTTPException(400, "action muss 'on' oder 'off' sein")

    # Energie VOR dem Ausschalten messen (danach liefert der Plug 0W)
    energy_wh = None
    if action == "off" and machine.session_started_at:
        pre_status = await get_plug_status(machine)
        if pre_status.get("power_w") is not None and pre_status["power_w"] > 0:
            duration_h = (datetime.utcnow() - machine.session_started_at).total_seconds() / 3600
            energy_wh = round(pre_status["power_w"] * duration_h, 3)

    ok, msg = await switch_plug(machine, action)

    if ok:
        if action == "on":
            try:
                await start_manager_session(db, machine, current.id)
            except Exception as e:
                log.error(f"start_manager_session Fehler: {e}", exc_info=True)
                raise HTTPException(500, f"Session-Start fehlgeschlagen: {str(e)}")
        else:
            await end_session(db, machine, ended_by=SessionEndedBy.manager, energy_wh=energy_wh)

    log_type = LogType.plug_on if action == "on" else LogType.plug_off
    await log_svc.log(db, log_type if ok else LogType.error,
        f"Manager {'EIN' if action == 'on' else 'AUS'}: {machine.name} — {msg}",
        machine_id=machine.id, user_id=current.id)

    return {"ok": ok, "action": action, "machine": machine.name, "message": msg}
