import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import qrcode

from app.database import get_db
from app.models import User, Machine, LogType
from app.services.auth import get_current_user
from app.services import logger as log_svc
from app.services.plug import switch_all_machine_plugs

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

    ok, msg = await switch_all_machine_plugs(machine, action, db)
    log_type = LogType.plug_on if action == "on" else LogType.plug_off
    await log_svc.log(
        db, log_type,
        f"Manuell {'EIN' if action == 'on' else 'AUS'}: {machine.name} — von {current.name}",
        machine_id=machine_id, user_id=current.id
    )
    return {"ok": ok, "message": msg}
