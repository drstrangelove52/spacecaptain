"""
Notfall-Alarm — Trigger, Cancel, Status
"""
import asyncio
import logging
from datetime import datetime
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import EmergencyState, NtfyTopic, LogType
from app.routers.auth import get_current_user
from app.services.auth import require_admin
from app.services.logger import log as activity_log
from app.services.system_settings import get_system_settings
from app.services.ntfy import send_notification
from app.services.plug import switch_plug

log = logging.getLogger(__name__)
router = APIRouter(prefix="/emergency", tags=["emergency"])


class CancelBody(BaseModel):
    comment: str = ""

# Laufender Auto-Stop Task
_auto_stop_task: asyncio.Task | None = None


async def _get_state(db: AsyncSession) -> EmergencyState:
    result = await db.execute(select(EmergencyState).where(EmergencyState.id == 1))
    state = result.scalar_one_or_none()
    if not state:
        state = EmergencyState(id=1, active=False)
        db.add(state)
        await db.flush()
    return state


async def _switch_emergency_plugs(cfg, action: str):
    """Schaltet Notfall-Plugs (Sirene + Licht) ein oder aus."""
    for ip, plug_type, plug_token in [
        (cfg.emergency_plug_ip,  cfg.emergency_plug_type,  cfg.emergency_plug_token),
        (cfg.emergency_plug2_ip, cfg.emergency_plug2_type, cfg.emergency_plug2_token),
    ]:
        if ip and plug_type and plug_type != "none":
            fake = SimpleNamespace(
                plug_type=plug_type, plug_ip=ip,
                plug_token=plug_token, plug_extra=None
            )
            ok, msg = await switch_plug(fake, action)
            log.info(f"Notfall-Plug {ip} ({plug_type}) {action}: {msg}")


@router.get("/status")
async def emergency_status(db: AsyncSession = Depends(get_db)):
    """Öffentlicher Endpunkt — wird vom Display gepollt."""
    state = await _get_state(db)
    cfg = await get_system_settings(db)
    return {
        "active": state.active,
        "triggered_at": state.triggered_at.isoformat() if state.triggered_at else None,
        "triggered_by": state.triggered_by,
        "emergency_text": cfg.emergency_text or "",
    }


@router.post("/trigger")
async def trigger_emergency(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Notfall auslösen — authentifiziert via X-Emergency-Token Header.
    Wird vom physischen Knopf (Shelly) aufgerufen.
    """
    cfg = await get_system_settings(db)

    # Token-Validierung
    if not cfg.emergency_trigger_token:
        raise HTTPException(403, "Kein Notfall-Token konfiguriert")
    token = request.headers.get("X-Emergency-Token", "")
    if token != cfg.emergency_trigger_token:
        raise HTTPException(403, "Ungültiger Token")

    state = await _get_state(db)
    if state.active:
        return {"ok": True, "message": "Notfall bereits aktiv"}

    state.active = True
    state.triggered_at = datetime.utcnow()
    client_ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                 or (request.client.host if request.client else "unbekannt"))
    state.triggered_by = client_ip
    await db.commit()

    # Plugs einschalten
    await _switch_emergency_plugs(cfg, "on")

    # ntfy-Benachrichtigung senden
    if cfg.emergency_ntfy_topic_id:
        result = await db.execute(
            select(NtfyTopic).where(NtfyTopic.id == cfg.emergency_ntfy_topic_id)
        )
        ntfy_topic = result.scalar_one_or_none()
        if ntfy_topic:
            ts = state.triggered_at.strftime("%d.%m.%Y %H:%M")
            default_msg = f"Notfall-Alarm ausgelöst am {ts}. Bitte sofort reagieren."
            ntfy_msg = (cfg.emergency_ntfy_message or default_msg).replace("{ts}", ts)
            await send_notification(
                server=cfg.ntfy_server or "https://ntfy.sh",
                token=cfg.ntfy_token,
                topic=ntfy_topic.topic,
                title="🚨 NOTFALL — Makerspace",
                message=ntfy_msg,
                priority="urgent",
                tags=["rotating_light", "sos"],
            )

    # Auto-Stop für Plugs planen (Display bleibt aktiv bis manuell quittiert)
    if cfg.emergency_duration_sec and cfg.emergency_duration_sec > 0:
        global _auto_stop_task
        if _auto_stop_task and not _auto_stop_task.done():
            _auto_stop_task.cancel()
        _auto_stop_task = asyncio.create_task(
            _auto_stop_plugs(cfg, cfg.emergency_duration_sec)
        )

    await activity_log(db, LogType.emergency_triggered,
                       f"Notfall-Alarm ausgelöst von: {state.triggered_by}")
    log.warning(f"NOTFALL ausgelöst von {state.triggered_by}")
    return {"ok": True, "message": "Notfall ausgelöst"}


@router.post("/cancel")
async def cancel_emergency(
    body: CancelBody,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Notfall quittieren — nur für authentifizierte Lab Manager."""
    global _auto_stop_task
    if _auto_stop_task and not _auto_stop_task.done():
        _auto_stop_task.cancel()
        _auto_stop_task = None

    state = await _get_state(db)
    state.active = False
    await db.commit()

    cfg = await get_system_settings(db)
    await _switch_emergency_plugs(cfg, "off")

    # ntfy-Benachrichtigung bei Quittierung
    if cfg.emergency_ntfy_topic_id:
        result = await db.execute(
            select(NtfyTopic).where(NtfyTopic.id == cfg.emergency_ntfy_topic_id)
        )
        ntfy_topic = result.scalar_one_or_none()
        if ntfy_topic:
            ts = datetime.utcnow().strftime("%d.%m.%Y %H:%M")
            msg = f"Notfall quittiert um {ts} von {current_user.name}."
            if body.comment:
                msg += f"\nKommentar: {body.comment}"
            await send_notification(
                server=cfg.ntfy_server or "https://ntfy.sh",
                token=cfg.ntfy_token,
                topic=ntfy_topic.topic,
                title="✅ Notfall quittiert",
                message=msg,
                priority="default",
                tags=["white_check_mark"],
            )

    log_msg = f"Notfall-Alarm quittiert von: {current_user.name}"
    if body.comment:
        log_msg += f" — {body.comment}"
    await activity_log(db, LogType.emergency_cancelled, log_msg, user_id=current_user.id)
    log.warning(f"NOTFALL quittiert von {current_user.name}")
    return {"ok": True}


async def _auto_stop_plugs(cfg, duration_sec: int):
    """Schaltet Plugs nach Ablauf der konfigurierten Dauer aus. Display bleibt aktiv."""
    try:
        await asyncio.sleep(duration_sec)
        await _switch_emergency_plugs(cfg, "off")
        log.info(f"Notfall-Plugs nach {duration_sec} Sekunden automatisch ausgeschaltet")
    except asyncio.CancelledError:
        pass
