"""
QR-Scan Router
==============
Ablauf:
  1. Gast öffnet Smartphone → scannt eigenen Login-QR  →  POST /api/qr/guest-login
     → erhält einen temporären Session-Token (15 min)

  2. Gast scannt QR-Code der Maschine  →  POST /api/qr/scan
     → Server prüft Berechtigung
     → Bei Erfolg: Smart Plug EIN, Nutzung wird geloggt
     → Bei Misserfolg: 403 + Log

  3. Gast scannt "Fertig"-QR oder drückt Button  →  POST /api/qr/release
     → Smart Plug AUS, Nutzung endet
"""
import io
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
import qrcode

from app.database import get_db
from app.models import User, Guest, Machine, Permission, GuestToken, LogType, MachineQueue, QueueStatus
from app.schemas import QRScanRequest
from app.services.auth import get_current_user
from app.services import logger as log_svc
from app.services.plug import switch_plug

router = APIRouter(prefix="/qr", tags=["qr"])


class RenderRequest(BaseModel):
    data: str

@router.get("/url-png")
async def url_qr_png(u: str):
    """Generiert einen QR-Code PNG für eine URL — öffentlich, kein Login (für Display-Seite)."""
    qr = qrcode.QRCode(version=1, box_size=8, border=3)
    qr.add_data(u)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


@router.post("/render")
async def render_qr(
    payload: RenderRequest,
    _: User = Depends(get_current_user),
):
    """Generiert einen QR-Code als PNG für einen beliebigen Inhalt (nur für eingeloggte Manager)."""
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(payload.data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

GUEST_TOKEN_MINUTES = 15


# ── 1. Gast-Login via QR ──────────────────────────────────────────────────────
@router.post("/guest-login/{guest_id}")
async def generate_guest_login(
    guest_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),  # nur Manager/Admin darf QR ausstellen
):
    """
    Generiert einen temporären Login-Token für einen Gast.
    Dieser Token wird als QR-Code auf dem Smartphone des Gastes gespeichert
    oder als Ausdruck mitgegeben.
    """
    result = await db.execute(select(Guest).where(Guest.id == guest_id, Guest.is_active == True))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")

    from app.services.system_settings import get_system_settings
    sysset = await get_system_settings(db)

    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(days=sysset.guest_token_days)

    gt = GuestToken(guest_id=guest_id, token=token, expires_at=expires)
    db.add(gt)
    await db.commit()

    return {
        "guest_id": guest_id,
        "guest_name": guest.name,
        "token": token,
        "expires_at": expires.isoformat(),
        "qr_data": token,  # Dieser Wert kommt in den QR-Code des Gastes
    }


# ── 2. Maschinen-Scan (Kernlogik) ─────────────────────────────────────────────
@router.post("/scan")
async def scan_machine(
    payload: QRScanRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Wird vom Smartphone aufgerufen wenn der Gast den Maschinen-QR scannt.
    Keine JWT-Auth nötig — Authentifizierung über guest_token.
    """
    # 1. Gast-Token validieren
    token_result = await db.execute(
        select(GuestToken).where(
            GuestToken.token == payload.guest_token,
            GuestToken.expires_at > datetime.utcnow()
        )
    )
    guest_token = token_result.scalar_one_or_none()
    if not guest_token:
        raise HTTPException(401, "Ungültiger oder abgelaufener Gast-Token")

    guest_result = await db.execute(
        select(Guest).where(Guest.id == guest_token.guest_id, Guest.is_active == True)
    )
    guest = guest_result.scalar_one_or_none()
    if not guest:
        raise HTTPException(403, "Gast nicht aktiv")

    # 2. Maschine via QR-Token finden
    machine_result = await db.execute(
        select(Machine).where(Machine.qr_token == payload.machine_qr)
    )
    machine = machine_result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    if machine.status != "online":
        await log_svc.log(
            db, LogType.access_denied,
            f"Maschine offline: {guest.name} → {machine.name}",
            guest_id=guest.id, machine_id=machine.id,
            meta={"reason": "machine_offline"}
        )
        raise HTTPException(503, f"Maschine '{machine.name}' ist nicht verfügbar")

    # 3. Berechtigung prüfen
    perm_result = await db.execute(
        select(Permission).where(
            Permission.guest_id == guest.id,
            Permission.machine_id == machine.id
        )
    )
    permission = perm_result.scalar_one_or_none()

    if not permission:
        await log_svc.log(
            db, LogType.access_denied,
            f"Zugang verweigert: {guest.name} → {machine.name} (keine Berechtigung)",
            guest_id=guest.id, machine_id=machine.id,
            meta={"reason": "no_permission"}
        )
        raise HTTPException(
            403,
            detail={
                "message": f"Keine Berechtigung für '{machine.name}'",
                "guest": guest.name,
                "machine": machine.name,
                "access": False,
            }
        )

    # 4. Warteliste: blockieren wenn der erste Eintrag in der Queue jemand anderem gehört
    first_res = await db.execute(
        select(MachineQueue).where(
            MachineQueue.machine_id == machine.id,
            MachineQueue.status.in_([QueueStatus.waiting, QueueStatus.notified]),
        ).order_by(MachineQueue.joined_at.asc()).limit(1)
    )
    notified = first_res.scalar_one_or_none()
    if notified and notified.guest_id != guest.id:
        await log_svc.log(
            db, LogType.access_denied,
            f"Zugang verweigert: {guest.name} → {machine.name} (Warteliste reserviert)",
            guest_id=guest.id, machine_id=machine.id,
            meta={"reason": "queue_reserved"}
        )
        raise HTTPException(
            423,
            detail={
                "message": f"'{machine.name}' ist gerade für einen anderen Gast in der Warteliste reserviert",
                "guest": guest.name,
                "machine": machine.name,
                "access": False,
            }
        )

    # 5. Queue-Eintrag des Gastes entfernen (Sitzung beginnt jetzt)
    await db.execute(delete(MachineQueue).where(
        MachineQueue.machine_id == machine.id,
        MachineQueue.guest_id == guest.id,
    ))

    # 6. Smart Plug einschalten
    plug_ok, plug_msg = await switch_plug(machine, "on")

    await log_svc.log(
        db, LogType.access_granted,
        f"Zugang gewährt: {guest.name} → {machine.name}",
        guest_id=guest.id, machine_id=machine.id,
        meta={"plug_ok": plug_ok, "plug_msg": plug_msg}
    )
    if plug_ok:
        await log_svc.log(
            db, LogType.plug_on,
            f"Steckdose EIN: {machine.name} ({machine.plug_type})",
            machine_id=machine.id, guest_id=guest.id
        )

    return {
        "access": True,
        "message": f"Willkommen, {guest.name}! {machine.name} ist freigegeben.",
        "guest": guest.name,
        "machine": machine.name,
        "plug_activated": plug_ok,
        "plug_message": plug_msg,
    }


# ── 3. Maschine freigeben (Plug AUS) ─────────────────────────────────────────
@router.post("/release")
async def release_machine(
    guest_token: str,
    machine_qr: str,
    db: AsyncSession = Depends(get_db),
):
    """Gast ist fertig — Maschine ausschalten."""
    token_result = await db.execute(
        select(GuestToken).where(GuestToken.token == guest_token)
    )
    gt = token_result.scalar_one_or_none()
    if not gt:
        raise HTTPException(401, "Ungültiger Token")

    machine_result = await db.execute(select(Machine).where(Machine.qr_token == machine_qr))
    machine = machine_result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    plug_ok, plug_msg = await switch_plug(machine, "off")

    await log_svc.log(
        db, LogType.plug_off,
        f"Steckdose AUS: {machine.name} — Gast-Token {guest_token[:8]}…",
        machine_id=machine.id
    )

    return {"ok": True, "plug_off": plug_ok, "message": plug_msg}


# ── Manuelles Steuern (Admin/Manager) ────────────────────────────────────────
@router.post("/plug/toggle")
async def manual_plug_toggle(
    machine_id: int,
    action: str,  # "on" | "off"
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Manager kann Steckdose manuell ein/ausschalten."""
    if action not in ("on", "off"):
        raise HTTPException(400, "action muss 'on' oder 'off' sein")

    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    ok, msg = await switch_plug(machine, action)
    log_type = LogType.plug_on if action == "on" else LogType.plug_off
    await log_svc.log(
        db, log_type,
        f"Manuell {'EIN' if action == 'on' else 'AUS'}: {machine.name} — von {current.name}",
        machine_id=machine_id, user_id=current.id
    )
    return {"ok": ok, "message": msg}
