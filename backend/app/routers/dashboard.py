from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import APP_TIMEZONE

def _local_iso(dt):
    """Konvertiert UTC datetime zu lokaler Zeitzone als ISO-String."""
    if dt is None:
        return None
    from datetime import timezone
    utc_dt = dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(APP_TIMEZONE).isoformat()
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models import User, Guest, Machine, Permission, ActivityLog, EmergencyState, MaintenanceInterval, MaintenanceRecord, MachineQueue, QueueStatus
from app.schemas import LogOut, DashboardStats
from app.services.auth import get_current_user
from app.services.system_settings import get_system_settings

router = APIRouter(tags=["dashboard & log"])

_AUTOMATION_TYPES = {"rule_on", "rule_off", "rule_notify", "room_opened", "room_closed"}
_SYSTEM_TYPES     = {"idle_timeout", "system"}

def _resolve_user_name(l, users: dict) -> str | None:
    if l.user_id:
        return users.get(l.user_id)
    stored = (l.meta or {}).get("user_name")
    if stored:
        return stored
    type_val = l.type.value if hasattr(l.type, "value") else str(l.type)
    if type_val in _AUTOMATION_TYPES:
        return "Automation"
    if type_val in _SYSTEM_TYPES:
        return "System"
    return None


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    total_guests     = (await db.execute(select(func.count()).select_from(Guest))).scalar() or 0
    active_guests    = (await db.execute(select(func.count()).where(Guest.is_active == True))).scalar() or 0
    total_machines   = (await db.execute(select(func.count()).select_from(Machine))).scalar() or 0
    online_machines  = (await db.execute(select(func.count()).where(Machine.status == "online"))).scalar() or 0
    total_managers   = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    total_permissions= (await db.execute(select(func.count()).select_from(Permission))).scalar() or 0
    return DashboardStats(
        total_guests=total_guests, active_guests=active_guests,
        total_machines=total_machines, online_machines=online_machines,
        total_managers=total_managers, total_permissions=total_permissions,
    )


@router.get("/log")
async def activity_log(
    limit:      int           = Query(100, ge=1, le=1000),
    offset:     int           = Query(0, ge=0),
    guest_id:   Optional[int] = Query(None),
    machine_id: Optional[int] = Query(None),
    user_id:    Optional[int] = Query(None),
    type:       Optional[str] = Query(None),   # einzelner Typ oder kommagetrennte Liste

    date_from:  Optional[str] = Query(None),   # ISO date "2025-01-01"
    date_to:    Optional[str] = Query(None),
    search:     Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    filters = []
    if guest_id:   filters.append(ActivityLog.guest_id == guest_id)
    if machine_id: filters.append(ActivityLog.machine_id == machine_id)
    if user_id:    filters.append(ActivityLog.user_id == user_id)
    if type:
        types = [t.strip() for t in type.split(",") if t.strip()]
        if len(types) == 1:
            filters.append(ActivityLog.type == types[0])
        else:
            filters.append(ActivityLog.type.in_(types))
    if date_from:
        try: filters.append(ActivityLog.created_at >= datetime.fromisoformat(date_from))
        except ValueError: pass
    if date_to:
        try: filters.append(ActivityLog.created_at <= datetime.fromisoformat(date_to + "T23:59:59"))
        except ValueError: pass
    if search:
        filters.append(ActivityLog.message.ilike(f"%{search}%"))

    q = select(ActivityLog)
    if filters:
        q = q.where(and_(*filters))

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0

    q = q.order_by(ActivityLog.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    logs = result.scalars().all()

    # Gast/Maschinen/User-Namen anhängen
    guests   = {g.id: g.name for g in (await db.execute(select(Guest))).scalars().all()}
    machines = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}
    users    = {u.id: u.name for u in (await db.execute(select(User))).scalars().all()}

    out = []
    for l in logs:
        out.append({
            "id":           l.id,
            "type":         l.type,
            "guest_id":     l.guest_id,
            "machine_id":   l.machine_id,
            "user_id":      l.user_id,
            "message":      l.message,
            "meta":         l.meta,
            "created_at":   _local_iso(l.created_at),
            "guest_name":   guests.get(l.guest_id)   if l.guest_id   else None,
            "machine_name": machines.get(l.machine_id) if l.machine_id else None,
            "user_name":    _resolve_user_name(l, users),
        })
    return {"total": total, "logs": out}


@router.get("/dashboard/summary")
async def dashboard_summary(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """Aggregiert alle Dashboard-Polling-Daten in einem einzigen Request."""
    from datetime import timezone

    # Pending Gäste
    pending_count = (await db.execute(
        select(func.count()).where(Guest.pending_approval == True)
    )).scalar() or 0

    # Wartung: due + warning zählen
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

    # Raum-Status
    settings = await get_system_settings(db)
    since_iso = None
    if settings.room_open_since:
        since_iso = settings.room_open_since.replace(tzinfo=timezone.utc).astimezone(APP_TIMEZONE).isoformat()

    # Notfall-Status
    em = (await db.execute(select(EmergencyState).where(EmergencyState.id == 1))).scalar_one_or_none()
    emergency_active = bool(em and em.active)
    triggered_at = None
    if em and em.triggered_at:
        triggered_at = em.triggered_at.replace(tzinfo=timezone.utc).astimezone(APP_TIMEZONE).isoformat()

    # Wartelisten-Einträge
    queue_count = (await db.execute(
        select(func.count()).where(MachineQueue.status.in_([QueueStatus.waiting, QueueStatus.notified]))
    )).scalar() or 0

    return {
        "pending_guests":    pending_count,
        "maintenance_due":   maintenance_due,
        "room_open":         settings.room_open,
        "room_open_since":   since_iso,
        "room_open_auto":    settings.room_open_auto,
        "emergency_active":  emergency_active,
        "triggered_at":      triggered_at,
        "queue_count":       queue_count,
    }


@router.get("/log/filter-options")
async def log_filter_options(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Gibt alle verfügbaren Filter-Optionen zurück (für Dropdowns)."""
    guests   = (await db.execute(select(Guest.id, Guest.name).order_by(Guest.name))).all()
    machines = (await db.execute(select(Machine.id, Machine.name).order_by(Machine.name))).all()
    users    = (await db.execute(select(User.id, User.name).order_by(User.name))).all()
    return {
        "guests":   [{"id": g.id, "name": g.name} for g in guests],
        "machines": [{"id": m.id, "name": m.name} for m in machines],
        "users":    [{"id": u.id, "name": u.name} for u in users],
        "types": [
            "access_granted", "access_denied", "plug_on", "plug_off",
            "guest_created", "guest_deleted", "machine_created", "machine_deleted",
            "permission_granted", "permission_revoked", "login", "error",
            "idle_off", "session_started", "maintenance_due", "maintenance_done"
        ]
    }
