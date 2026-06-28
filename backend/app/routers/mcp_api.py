"""Interne API-Endpunkte für den MCP-Server. Auth via X-MCP-Key Header (DB-Token)."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timezone

from app.database import get_db
from app.models import (Machine, Guest, ActivityLog, MaintenanceInterval,
                         MaintenanceRecord, EmergencyState, MachineQueue, QueueStatus, User)
from app.services.system_settings import get_system_settings
from app.config import APP_TIMEZONE

router = APIRouter(prefix="/mcp", tags=["mcp"])


async def require_mcp(
    x_mcp_key: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    sys = await get_system_settings(db)
    if not sys.mcp_enabled:
        raise HTTPException(503, "MCP nicht aktiviert")
    if not sys.mcp_api_token or x_mcp_key != sys.mcp_api_token:
        raise HTTPException(403, "Ungültiger MCP-Key")


@router.get("/bootstrap-token")
async def mcp_bootstrap_token(db: AsyncSession = Depends(get_db)):
    """Intern: MCP-Server lädt Token beim Start. Nur aus Docker-internem Netz erreichbar."""
    sys = await get_system_settings(db)
    if not sys.mcp_enabled or not sys.mcp_api_token:
        raise HTTPException(503, "MCP nicht aktiv oder kein Token konfiguriert")
    return {"token": sys.mcp_api_token}


@router.get("/status")
async def mcp_get_status(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    pending = (await db.execute(
        select(func.count()).where(Guest.pending_approval == True)
    )).scalar() or 0

    intervals = (await db.execute(
        select(MaintenanceInterval).where(MaintenanceInterval.is_active == True)
    )).scalars().all()
    machines_map = {m.id: m for m in (await db.execute(select(Machine))).scalars().all()}
    maintenance_due = 0
    now = datetime.utcnow()
    for iv in intervals:
        machine = machines_map.get(iv.machine_id)
        if not machine:
            continue
        last = (await db.execute(
            select(MaintenanceRecord)
            .where(MaintenanceRecord.interval_id == iv.id)
            .order_by(MaintenanceRecord.performed_at.desc()).limit(1)
        )).scalars().first()
        base_hours = last.hours_at_execution if last else 0.0
        base_time  = last.performed_at if last else iv.created_at
        hours_since = (machine.total_hours or 0.0) - (base_hours or 0.0)
        days_since  = (now - base_time).total_seconds() / 86400
        is_due = (
            (iv.interval_hours and (iv.interval_hours - hours_since) <= 0) or
            (iv.interval_days  and (iv.interval_days  - days_since)  <= 0)
        )
        is_warning = not is_due and (
            (iv.interval_hours and iv.warning_hours is not None and (iv.interval_hours - hours_since) <= iv.warning_hours) or
            (iv.interval_days  and iv.warning_days  is not None and (iv.interval_days  - days_since)  <= iv.warning_days)
        )
        if is_due or is_warning:
            maintenance_due += 1

    s = await get_system_settings(db)
    since_iso = None
    if s.room_open_since:
        since_iso = s.room_open_since.replace(tzinfo=timezone.utc).astimezone(APP_TIMEZONE).isoformat()

    em = (await db.execute(select(EmergencyState).where(EmergencyState.id == 1))).scalar_one_or_none()
    emergency_active = bool(em and em.active)
    triggered_at = None
    if em and em.triggered_at:
        triggered_at = em.triggered_at.replace(tzinfo=timezone.utc).astimezone(APP_TIMEZONE).isoformat()

    queue_count = (await db.execute(
        select(func.count()).where(MachineQueue.status.in_([QueueStatus.waiting, QueueStatus.notified]))
    )).scalar() or 0

    return {
        "pending_guests":   pending,
        "maintenance_due":  maintenance_due,
        "room_open":        s.room_open,
        "room_open_since":  since_iso,
        "emergency_active": emergency_active,
        "triggered_at":     triggered_at,
        "queue_count":      queue_count,
        "space_name":       s.space_name or "SpaceCaptain",
    }


@router.get("/machines")
async def mcp_list_machines(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    machines = (await db.execute(select(Machine))).scalars().all()
    guests   = {g.id: g.name for g in (await db.execute(select(Guest))).scalars().all()}
    return [
        {
            "id":           m.id,
            "name":         m.name,
            "category":     m.category,
            "location":     m.location,
            "status":       m.status,
            "in_use":       m.current_guest_id is not None,
            "current_guest": guests.get(m.current_guest_id) if m.current_guest_id else None,
            "session_started_at": m.session_started_at.isoformat() if m.session_started_at else None,
            "total_hours":  round(m.total_hours or 0, 1),
        }
        for m in machines
    ]


@router.post("/room")
async def mcp_set_room(payload: dict, db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    from app.services.room import open_room, close_room
    open_val = bool(payload.get("open", False))
    if open_val:
        await open_room(db, user_id=None)
    else:
        await close_room(db, user_id=None)
    return {"room_open": open_val, "ok": True}


@router.get("/guests/pending")
async def mcp_pending_guests(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    guests = (await db.execute(
        select(Guest).where(Guest.pending_approval == True)
    )).scalars().all()
    return [
        {"id": g.id, "name": g.name, "username": g.username,
         "email": g.email, "created_at": g.created_at.isoformat()}
        for g in guests
    ]


@router.post("/guests/{guest_id}/approve")
async def mcp_approve_guest(guest_id: int, db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    guest = (await db.execute(select(Guest).where(Guest.id == guest_id))).scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")
    guest.pending_approval = False
    guest.is_active = True
    await db.commit()
    return {"ok": True, "guest": guest.name}


@router.get("/log")
async def mcp_activity_log(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_mcp),
):
    logs = (await db.execute(
        select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit)
    )).scalars().all()
    guests   = {g.id: g.name for g in (await db.execute(select(Guest))).scalars().all()}
    machines = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}
    users    = {u.id: u.name for u in (await db.execute(select(User))).scalars().all()}
    return {
        "logs": [
            {
                "id":           l.id,
                "type":         l.type,
                "message":      l.message,
                "created_at":   l.created_at.replace(tzinfo=timezone.utc).astimezone(APP_TIMEZONE).isoformat(),
                "guest_name":   guests.get(l.guest_id)   if l.guest_id   else None,
                "machine_name": machines.get(l.machine_id) if l.machine_id else None,
                "user_name":    users.get(l.user_id)     if l.user_id    else None,
            }
            for l in logs
        ]
    }


@router.post("/update")
async def mcp_trigger_update(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    from pathlib import Path
    trigger_file = Path("/app/update_trigger/trigger")
    if not trigger_file.parent.exists():
        raise HTTPException(503, "Update-Trigger-Verzeichnis nicht verfügbar")
    trigger_file.write_text(datetime.now().isoformat())
    return {"ok": True, "message": "Update ausgelöst"}
