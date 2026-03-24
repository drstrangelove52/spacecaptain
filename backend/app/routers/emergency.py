"""
Notfall-Alarm — Trigger, Cancel, Status
"""
import asyncio
import logging
from datetime import datetime
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import EmergencyState, NtfyTopic
from app.services.auth import require_admin
from app.services.system_settings import get_system_settings
from app.services.ntfy import send_notification
from app.services.plug import switch_plug

log = logging.getLogger(__name__)
router = APIRouter(prefix="/emergency", tags=["emergency"])

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
    for ip, plug_type in [
        (cfg.emergency_plug_ip,  cfg.emergency_plug_type),
        (cfg.emergency_plug2_ip, cfg.emergency_plug2_type),
    ]:
        if ip and plug_type and plug_type != "none":
            fake = SimpleNamespace(
                plug_type=plug_type, plug_ip=ip,
                plug_token=None, plug_extra=None
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
    state.triggered_by = request.headers.get("X-Triggered-By", "button")
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
            await send_notification(
                server=cfg.ntfy_server or "https://ntfy.sh",
                token=cfg.ntfy_token,
                topic=ntfy_topic.topic,
                title="🚨 NOTFALL — Makerspace",
                message=f"Notfall-Alarm ausgelöst am {ts}. Bitte sofort reagieren.",
                priority="urgent",
                tags=["rotating_light", "sos"],
            )

    # Auto-Stop für Plugs planen (Display bleibt aktiv bis manuell quittiert)
    if cfg.emergency_duration_min and cfg.emergency_duration_min > 0:
        global _auto_stop_task
        if _auto_stop_task and not _auto_stop_task.done():
            _auto_stop_task.cancel()
        _auto_stop_task = asyncio.create_task(
            _auto_stop_plugs(cfg, cfg.emergency_duration_min)
        )

    log.warning(f"NOTFALL ausgelöst von {state.triggered_by}")
    return {"ok": True, "message": "Notfall ausgelöst"}


@router.post("/cancel")
async def cancel_emergency(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
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

    log.warning("NOTFALL quittiert")
    return {"ok": True}


async def _auto_stop_plugs(cfg, duration_min: int):
    """Schaltet Plugs nach Ablauf der konfigurierten Dauer aus. Display bleibt aktiv."""
    try:
        await asyncio.sleep(duration_min * 60)
        await _switch_emergency_plugs(cfg, "off")
        log.info(f"Notfall-Plugs nach {duration_min} Minuten automatisch ausgeschaltet")
    except asyncio.CancelledError:
        pass
