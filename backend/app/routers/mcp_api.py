"""Interne API-Endpunkte für den MCP-Server. Auth via X-MCP-Key Header (DB-Token)."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timezone

from app.database import get_db
from app.models import (Machine, Guest, ActivityLog, MaintenanceInterval,
                         MaintenanceRecord, EmergencyState, MachineQueue, QueueStatus, User,
                         Permission, NtfyTopic, Plug, Announcement, MachineSession,
                         AutomationRule, RuleCondition, MachineCategory, MachineLocation,
                         MachineOwner, SessionEndedBy, Battery)
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
    owners   = {o.id: o.name for o in (await db.execute(select(MachineOwner))).scalars().all()}
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
            "purchase_date": m.purchase_date.isoformat() if m.purchase_date else None,
            "value_new":    m.value_new,
            "owner":        owners.get(m.owner_id) if m.owner_id else None,
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
    limit: int | None = Query(None, ge=1, description="Einträge pro Seite. Ohne Angabe: alle."),
    offset: int       = Query(0, ge=0),
    from_date: str | None = Query(None, description="ISO-Datum, z.B. 2026-01-01"),
    to_date: str | None   = Query(None, description="ISO-Datum, z.B. 2026-06-30"),
    log_type: str | None  = Query(None, description="Typ-Filter, z.B. session_start"),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_mcp),
):
    conditions = []
    if from_date:
        conditions.append(ActivityLog.created_at >= datetime.fromisoformat(from_date))
    if to_date:
        to_dt = datetime.fromisoformat(to_date).replace(hour=23, minute=59, second=59)
        conditions.append(ActivityLog.created_at <= to_dt)
    if log_type:
        conditions.append(ActivityLog.type == log_type)

    q = select(ActivityLog).order_by(ActivityLog.created_at.desc()).offset(offset)
    if conditions:
        q = q.where(and_(*conditions))
    if limit is not None:
        q = q.limit(limit)

    logs = (await db.execute(q)).scalars().all()

    total = (await db.scalar(
        select(func.count()).select_from(ActivityLog).where(and_(*conditions)) if conditions
        else select(func.count()).select_from(ActivityLog)
    )) or 0

    guests   = {g.id: g.name for g in (await db.execute(select(Guest))).scalars().all()}
    machines = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}
    users    = {u.id: u.name for u in (await db.execute(select(User))).scalars().all()}
    return {
        "total":  total,
        "offset": offset,
        "limit":  limit,
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
        ],
    }


@router.post("/update")
async def mcp_trigger_update(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    from pathlib import Path
    trigger_file = Path("/app/update_trigger/trigger")
    if not trigger_file.parent.exists():
        raise HTTPException(503, "Update-Trigger-Verzeichnis nicht verfügbar")
    if trigger_file.exists() or Path("/app/update_trigger/restart").exists() or Path("/app/update_trigger/restart_all").exists():
        raise HTTPException(409, "Vorgang läuft bereits")
    trigger_file.write_text(datetime.now().isoformat())
    return {"ok": True, "message": "Update ausgelöst"}


@router.post("/restart-backend")
async def mcp_restart_backend(_=Depends(require_mcp)):
    from pathlib import Path
    trigger_dir = Path("/app/update_trigger")
    if not trigger_dir.exists():
        raise HTTPException(503, "Update-Trigger-Verzeichnis nicht verfügbar")
    if (trigger_dir / "trigger").exists() or (trigger_dir / "restart").exists() or (trigger_dir / "restart_all").exists():
        raise HTTPException(409, "Vorgang läuft bereits")
    (trigger_dir / "restart").write_text(datetime.now().isoformat())
    return {"ok": True, "message": "Backend-Neustart ausgelöst"}


@router.post("/restart-all")
async def mcp_restart_all(_=Depends(require_mcp)):
    from pathlib import Path
    trigger_dir = Path("/app/update_trigger")
    if not trigger_dir.exists():
        raise HTTPException(503, "Update-Trigger-Verzeichnis nicht verfügbar")
    if (trigger_dir / "trigger").exists() or (trigger_dir / "restart").exists() or (trigger_dir / "restart_all").exists():
        raise HTTPException(409, "Vorgang läuft bereits")
    (trigger_dir / "restart_all").write_text(datetime.now().isoformat())
    return {"ok": True, "message": "Neustart aller Container ausgelöst"}


@router.post("/backup")
async def mcp_trigger_backup(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    from app.services.backup_service import _create_backup
    path = await _create_backup(db)
    return {"ok": True, "message": f"Backup erstellt: {path.name}"}


# ── Wartung ────────────────────────────────────────────────────────────────────

@router.get("/maintenance/due")
async def mcp_maintenance_due(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Alle fälligen und warnenden Wartungsintervalle mit Maschinennamen."""
    intervals = (await db.execute(
        select(MaintenanceInterval).where(MaintenanceInterval.is_active == True)
    )).scalars().all()
    machines_map = {m.id: m for m in (await db.execute(select(Machine))).scalars().all()}
    now = datetime.utcnow()
    result = []
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
            result.append({
                "interval_id":   iv.id,
                "interval_name": iv.name,
                "description":   iv.description,
                "machine_id":    machine.id,
                "machine_name":  machine.name,
                "status":        "due" if is_due else "warning",
                "hours_since":   round(hours_since, 1),
                "days_since":    round(days_since, 1),
                "interval_hours": iv.interval_hours,
                "interval_days":  iv.interval_days,
                "last_done":     last.performed_at.isoformat() if last else None,
            })
    return result


@router.post("/maintenance/record")
async def mcp_log_maintenance(payload: dict, db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Wartung erfassen. interval_id oder (machine_id + name) erforderlich."""
    from app.models import LogType
    from app.services import logger as log_svc
    interval_id = payload.get("interval_id")
    machine_id  = payload.get("machine_id")
    notes       = payload.get("notes", "")
    name        = payload.get("name", "")

    iv = machine = None
    if interval_id:
        iv = await db.get(MaintenanceInterval, int(interval_id))
        if not iv:
            raise HTTPException(404, "Intervall nicht gefunden")
        machine = await db.get(Machine, iv.machine_id)
    else:
        if not machine_id or not name:
            raise HTTPException(400, "interval_id oder (machine_id + name) erforderlich")
        machine = await db.get(Machine, int(machine_id))
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    record_name = iv.name if iv else name
    sys = await get_system_settings(db)
    record = MaintenanceRecord(
        interval_id=iv.id if iv else None,
        name=record_name,
        machine_id=machine.id,
        performed_by=sys.mcp_user_id,
        performed_at=datetime.utcnow(),
        hours_at_execution=machine.total_hours,
        notes=notes,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    await log_svc.log(
        db, LogType.maintenance_done,
        f"Wartung dokumentiert (MCP): «{record_name}» an {machine.name} — {machine.total_hours:.1f} h",
        machine_id=machine.id,
        meta={"interval_id": iv.id if iv else None, "notes": notes},
    )
    return {"ok": True, "record_id": record.id, "machine": machine.name, "interval": record_name}


# ── Gäste ──────────────────────────────────────────────────────────────────────

@router.get("/guests")
async def mcp_list_guests(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Alle Gäste mit Status."""
    guests = (await db.execute(select(Guest).order_by(Guest.name))).scalars().all()
    return [
        {
            "id":               g.id,
            "name":             g.name,
            "username":         g.username,
            "email":            g.email,
            "is_active":        g.is_active,
            "is_blocked":       g.is_blocked,
            "pending_approval": g.pending_approval,
            "created_at":       g.created_at.isoformat(),
        }
        for g in guests
    ]


@router.patch("/guests/{guest_id}/block")
async def mcp_set_guest_blocked(
    guest_id: int, payload: dict,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Gast sperren (blocked=True) oder entsperren (blocked=False)."""
    guest = (await db.execute(select(Guest).where(Guest.id == guest_id))).scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")
    guest.is_blocked = bool(payload.get("blocked", True))
    await db.commit()
    return {"ok": True, "guest": guest.name, "is_blocked": guest.is_blocked}


@router.get("/guests/{guest_id}/permissions")
async def mcp_guest_permissions(
    guest_id: int,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Maschinenberechtigungen eines Gastes."""
    guest = (await db.execute(select(Guest).where(Guest.id == guest_id))).scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")
    perms = (await db.execute(
        select(Permission).where(Permission.guest_id == guest_id)
    )).scalars().all()
    machines_map = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}
    return {
        "guest_id":   guest_id,
        "guest_name": guest.name,
        "permissions": [
            {
                "machine_id":   p.machine_id,
                "machine_name": machines_map.get(p.machine_id, "?"),
                "is_blocked":   p.is_blocked,
                "granted_at":   p.granted_at.isoformat(),
            }
            for p in perms
        ],
    }


@router.post("/guests/{guest_id}/permissions/{machine_id}")
async def mcp_set_permission(
    guest_id: int, machine_id: int, payload: dict,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Maschinenberechtigung vergeben (grant=True) oder entziehen (grant=False)."""
    from app.models import LogType
    from app.services import logger as log_svc
    guest   = (await db.execute(select(Guest).where(Guest.id == guest_id))).scalar_one_or_none()
    machine = await db.get(Machine, machine_id)
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    grant = bool(payload.get("grant", True))
    perm  = (await db.execute(
        select(Permission).where(Permission.guest_id == guest_id, Permission.machine_id == machine_id)
    )).scalar_one_or_none()

    if grant:
        if not perm:
            perm = Permission(guest_id=guest_id, machine_id=machine_id, is_blocked=False)
            db.add(perm)
        else:
            perm.is_blocked = False
        await log_svc.log(db, LogType.permission_granted,
            f"Berechtigung vergeben (MCP): {guest.name} → {machine.name}",
            guest_id=guest_id, machine_id=machine_id)
    else:
        if perm:
            await db.delete(perm)
        await log_svc.log(db, LogType.permission_revoked,
            f"Berechtigung entzogen (MCP): {guest.name} → {machine.name}",
            guest_id=guest_id, machine_id=machine_id)

    await db.commit()
    return {"ok": True, "guest": guest.name, "machine": machine.name, "granted": grant}


# ── Maschinen ──────────────────────────────────────────────────────────────────

@router.get("/machines/{machine_id}")
async def mcp_get_machine(
    machine_id: int,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Einzelne Maschine mit laufender Session, Plug-Status und Wartungshistorie."""
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")
    guest = None
    if machine.current_guest_id:
        g = await db.get(Guest, machine.current_guest_id)
        guest = g.name if g else None
    plug = await db.get(Plug, machine.plug_id) if machine.plug_id else None
    owner = await db.get(MachineOwner, machine.owner_id) if machine.owner_id else None
    records = (await db.execute(
        select(MaintenanceRecord)
        .where(MaintenanceRecord.machine_id == machine_id)
        .order_by(MaintenanceRecord.performed_at.desc())
        .limit(5)
    )).scalars().all()
    users_map = {u.id: u.name for u in (await db.execute(select(User))).scalars().all()}
    return {
        "id":            machine.id,
        "name":          machine.name,
        "category":      machine.category,
        "location":      machine.location,
        "status":        machine.status,
        "total_hours":   round(machine.total_hours or 0, 1),
        "in_use":        machine.current_guest_id is not None,
        "current_guest": guest,
        "session_started_at": machine.session_started_at.isoformat() if machine.session_started_at else None,
        "purchase_date": machine.purchase_date.isoformat() if machine.purchase_date else None,
        "value_new":     machine.value_new,
        "owner":         owner.name if owner else None,
        "plug": {
            "id": plug.id, "ip": plug.plug_ip, "type": plug.plug_type,
        } if plug else None,
        "recent_maintenance": [
            {
                "name":         r.name,
                "performed_at": r.performed_at.isoformat(),
                "performed_by": users_map.get(r.performed_by) if r.performed_by else None,
                "notes":        r.notes,
            }
            for r in records
        ],
    }


@router.get("/maintenance/history")
async def mcp_maintenance_history(
    machine_id: int = Query(...),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Wartungshistorie einer Maschine (neueste zuerst)."""
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")
    records = (await db.execute(
        select(MaintenanceRecord)
        .where(MaintenanceRecord.machine_id == machine_id)
        .order_by(MaintenanceRecord.performed_at.desc())
        .limit(limit)
    )).scalars().all()
    users_map = {u.id: u.name for u in (await db.execute(select(User))).scalars().all()}
    return {
        "machine_id":   machine_id,
        "machine_name": machine.name,
        "records": [
            {
                "id":           r.id,
                "name":         r.name,
                "performed_at": r.performed_at.isoformat(),
                "performed_by": users_map.get(r.performed_by) if r.performed_by else None,
                "hours_at_execution": r.hours_at_execution,
                "notes":        r.notes,
            }
            for r in records
        ],
    }


@router.patch("/machines/{machine_id}/status")
async def mcp_set_machine_status(
    machine_id: int, payload: dict,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Maschinenstatus setzen: online | offline | maintenance.
    Entspricht im UI "Freigegeben"/"Gesperrt"/"In Wartung"."""
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")
    status = payload.get("status", "online")
    if status not in ("online", "offline", "maintenance"):
        raise HTTPException(400, "Status muss online, offline oder maintenance sein")
    machine.status = status
    await db.commit()
    return {"ok": True, "machine": machine.name, "status": status}


# ── Notfall ────────────────────────────────────────────────────────────────────

@router.post("/emergency")
async def mcp_set_emergency(
    payload: dict,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Notfall-Alarm auslösen (active=True) oder beenden (active=False)."""
    from app.routers.emergency import _switch_emergency_plugs
    active = bool(payload.get("active", True))
    sys = await get_system_settings(db)
    em = (await db.execute(select(EmergencyState).where(EmergencyState.id == 1))).scalar_one_or_none()
    if not em:
        em = EmergencyState(id=1, active=False)
        db.add(em)
    em.active = active
    if active:
        em.triggered_at = datetime.utcnow()
    await db.commit()
    action = "on" if active else "off"
    await _switch_emergency_plugs(sys.emergency_plug_id, sys.emergency_plug2_id, action, db)
    return {"ok": True, "emergency_active": active}


# ── Push-Nachrichten ───────────────────────────────────────────────────────────

@router.post("/notify")
async def mcp_send_notification(
    payload: dict,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Push-Nachricht senden. topic_id oder topic_key erforderlich."""
    from app.services.ntfy import send_notification
    topic_id  = payload.get("topic_id")
    topic_key = payload.get("topic_key")
    title     = payload.get("title", "SpaceCaptain")
    message   = payload.get("message", "")
    priority  = payload.get("priority", "default")

    topic_obj = None
    if topic_id:
        topic_obj = (await db.execute(select(NtfyTopic).where(NtfyTopic.id == int(topic_id)))).scalar_one_or_none()
    elif topic_key:
        topic_obj = (await db.execute(select(NtfyTopic).where(NtfyTopic.key == topic_key))).scalar_one_or_none()
    if not topic_obj:
        raise HTTPException(404, "Ntfy-Topic nicht gefunden")

    sys = await get_system_settings(db)
    server = sys.ntfy_server or "https://ntfy.sh"
    ok = await send_notification(
        server=server, token=sys.ntfy_token,
        topic=topic_obj.topic, title=title, message=message, priority=priority,
    )
    return {"ok": ok, "topic": topic_obj.topic}


@router.get("/notify/topics")
async def mcp_list_topics(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Alle konfigurierten ntfy-Topics."""
    topics = (await db.execute(select(NtfyTopic).order_by(NtfyTopic.title))).scalars().all()
    return [{"id": t.id, "key": t.key, "title": t.title, "topic": t.topic} for t in topics]


# ── Plugs ──────────────────────────────────────────────────────────────────────

@router.get("/plugs")
async def mcp_list_plugs(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Plug-Pool mit zugewiesenen Maschinen."""
    plugs = (await db.execute(select(Plug).order_by(Plug.label))).scalars().all()
    machines_map = {m.plug_id: m.name for m in (await db.execute(select(Machine))).scalars().all() if m.plug_id}
    return [
        {
            "id":       p.id,
            "label":    p.label,
            "ip":       p.ip,
            "type":     p.plug_type,
            "machine":  machines_map.get(p.id),
        }
        for p in plugs
    ]


# ── Aushänge ───────────────────────────────────────────────────────────────────

@router.get("/announcements")
async def mcp_list_announcements(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Alle Aushänge (aktiv und inaktiv)."""
    announcements = (await db.execute(
        select(Announcement).order_by(Announcement.created_at.desc())
    )).scalars().all()
    return [
        {
            "id":           a.id,
            "text":         a.text,
            "is_active":    a.is_active,
            "is_recurring": a.is_recurring,
            "display_type": a.display_type,
            "start_at":     a.start_at.isoformat() if a.start_at else None,
            "end_at":       a.end_at.isoformat() if a.end_at else None,
        }
        for a in announcements
    ]


@router.post("/announcements")
async def mcp_create_announcement(
    payload: dict,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Aushang erstellen. text und start_at + end_at (ISO) erforderlich."""
    text     = payload.get("text", "").strip()
    start_at = payload.get("start_at")
    end_at   = payload.get("end_at")
    if not text or not start_at or not end_at:
        raise HTTPException(400, "text, start_at und end_at erforderlich")
    try:
        start_dt = datetime.fromisoformat(start_at.replace("Z", "+00:00")).replace(tzinfo=None)
        end_dt   = datetime.fromisoformat(end_at.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(400, "Ungültiges Datumsformat (ISO 8601 erwartet)")
    a = Announcement(
        text=text, start_at=start_dt, end_at=end_dt,
        is_active=True, display_type=payload.get("display_type", "banner"),
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return {"ok": True, "id": a.id, "text": a.text}


@router.patch("/announcements/{announcement_id}")
async def mcp_update_announcement(
    announcement_id: int, payload: dict,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Aushang bearbeiten (text, is_active, start_at, end_at)."""
    a = await db.get(Announcement, announcement_id)
    if not a:
        raise HTTPException(404, "Aushang nicht gefunden")
    if "text" in payload:
        a.text = payload["text"].strip()
    if "is_active" in payload:
        a.is_active = bool(payload["is_active"])
    if "start_at" in payload and payload["start_at"]:
        a.start_at = datetime.fromisoformat(payload["start_at"].replace("Z", "+00:00")).replace(tzinfo=None)
    if "end_at" in payload and payload["end_at"]:
        a.end_at = datetime.fromisoformat(payload["end_at"].replace("Z", "+00:00")).replace(tzinfo=None)
    await db.commit()
    return {"ok": True, "id": a.id, "text": a.text, "is_active": a.is_active}


@router.delete("/announcements/{announcement_id}")
async def mcp_delete_announcement(
    announcement_id: int,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Aushang löschen."""
    a = await db.get(Announcement, announcement_id)
    if not a:
        raise HTTPException(404, "Aushang nicht gefunden")
    await db.delete(a)
    await db.commit()
    return {"ok": True}


# ── Statistiken ────────────────────────────────────────────────────────────────

@router.get("/stats")
async def mcp_get_stats(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Nutzungsstatistiken: Maschinen, Gäste, Sessions."""
    from sqlalchemy import desc
    total_guests   = (await db.scalar(select(func.count()).select_from(Guest))) or 0
    active_guests  = (await db.scalar(select(func.count()).where(Guest.is_active == True, Guest.is_blocked == False, Guest.pending_approval == False))) or 0
    blocked_guests = (await db.scalar(select(func.count()).where(Guest.is_blocked == True))) or 0
    pending_guests = (await db.scalar(select(func.count()).where(Guest.pending_approval == True))) or 0
    total_machines = (await db.scalar(select(func.count()).select_from(Machine))) or 0
    online_machines = (await db.scalar(select(func.count()).where(Machine.status == "online"))) or 0
    active_sessions = (await db.scalar(select(func.count()).where(MachineSession.ended_at.is_(None)))) or 0
    total_sessions  = (await db.scalar(select(func.count()).select_from(MachineSession))) or 0
    machines = (await db.execute(select(Machine).order_by(desc(Machine.total_hours)).limit(5))).scalars().all()
    return {
        "guests": {
            "total": total_guests,
            "active": active_guests,
            "blocked": blocked_guests,
            "pending": pending_guests,
        },
        "machines": {
            "total": total_machines,
            "online": online_machines,
            "active_sessions": active_sessions,
            "total_sessions": total_sessions,
        },
        "top_machines_by_hours": [
            {"id": m.id, "name": m.name, "total_hours": round(m.total_hours or 0, 1)}
            for m in machines
        ],
    }


@router.get("/inventory/value")
async def mcp_get_inventory_value(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Gesamtwert des Maschinenparks (Summe Neuwert) für Buchhaltung/Versicherung."""
    settings = await get_system_settings(db)
    machines = (await db.execute(select(Machine))).scalars().all()
    with_value = [m for m in machines if m.value_new is not None]
    return {
        "currency":              settings.currency or "CHF",
        "total_machines":        len(machines),
        "machines_with_value":   len(with_value),
        "machines_without_value": len(machines) - len(with_value),
        "total_value_new":       round(sum(m.value_new for m in with_value), 2),
    }


@router.get("/stats/sessions")
async def mcp_get_session_stats(
    from_date: str | None = Query(None, description="ISO-Datum, z.B. 2026-01-01"),
    to_date: str | None   = Query(None, description="ISO-Datum, z.B. 2026-06-30"),
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Zeitraum-Auswertung aller Sessions: Gesamtstunden, Durchschnittsdauer, Top-Maschinen, Top-Gäste."""
    from sqlalchemy import desc, case
    conditions = [MachineSession.ended_at.isnot(None)]
    if from_date:
        conditions.append(MachineSession.started_at >= datetime.fromisoformat(from_date))
    if to_date:
        to_dt = datetime.fromisoformat(to_date).replace(hour=23, minute=59, second=59)
        conditions.append(MachineSession.started_at <= to_dt)

    sessions = (await db.execute(
        select(MachineSession).where(and_(*conditions)).order_by(MachineSession.started_at)
    )).scalars().all()

    machines_map = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}
    guests_map   = {g.id: g.name for g in (await db.execute(select(Guest))).scalars().all()}

    total_sessions = len(sessions)
    total_minutes  = sum(s.duration_min or 0 for s in sessions)
    total_hours    = round(total_minutes / 60, 1)
    avg_duration_min = round(total_minutes / total_sessions, 1) if total_sessions else 0

    # Tagesweise Gruppierung
    from collections import defaultdict
    daily: dict[str, int] = defaultdict(int)
    for s in sessions:
        day = s.started_at.strftime("%Y-%m-%d")
        daily[day] += 1

    # Top-Maschinen nach Anzahl Sessions
    machine_counts: dict[int, dict] = defaultdict(lambda: {"sessions": 0, "minutes": 0.0})
    for s in sessions:
        machine_counts[s.machine_id]["sessions"] += 1
        machine_counts[s.machine_id]["minutes"] += s.duration_min or 0
    top_machines = sorted(machine_counts.items(), key=lambda x: x[1]["sessions"], reverse=True)[:5]

    # Top-Gäste nach Anzahl Sessions
    guest_counts: dict[int, dict] = defaultdict(lambda: {"sessions": 0, "minutes": 0.0})
    for s in sessions:
        if s.guest_id:
            guest_counts[s.guest_id]["sessions"] += 1
            guest_counts[s.guest_id]["minutes"] += s.duration_min or 0
    top_guests = sorted(guest_counts.items(), key=lambda x: x[1]["sessions"], reverse=True)[:5]

    return {
        "period": {"from": from_date, "to": to_date},
        "sessions": {
            "total": total_sessions,
            "total_hours": total_hours,
            "avg_duration_min": avg_duration_min,
        },
        "by_day": [{"date": d, "sessions": c} for d, c in sorted(daily.items())],
        "top_machines": [
            {
                "id": mid,
                "name": machines_map.get(mid, "?"),
                "sessions": v["sessions"],
                "hours": round(v["minutes"] / 60, 1),
            }
            for mid, v in top_machines
        ],
        "top_guests": [
            {
                "id": gid,
                "name": guests_map.get(gid, "?"),
                "sessions": v["sessions"],
                "hours": round(v["minutes"] / 60, 1),
            }
            for gid, v in top_guests
        ],
    }


@router.get("/stats/machines/{machine_id}")
async def mcp_get_machine_stats(
    machine_id: int,
    from_date: str | None = Query(None),
    to_date: str | None   = Query(None),
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Detaillierte Auslastungsauswertung einer Maschine: Wochentrend, Top-Gäste, Avg-Dauer."""
    from collections import defaultdict
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    conditions = [MachineSession.machine_id == machine_id, MachineSession.ended_at.isnot(None)]
    if from_date:
        conditions.append(MachineSession.started_at >= datetime.fromisoformat(from_date))
    if to_date:
        to_dt = datetime.fromisoformat(to_date).replace(hour=23, minute=59, second=59)
        conditions.append(MachineSession.started_at <= to_dt)

    sessions = (await db.execute(
        select(MachineSession).where(and_(*conditions)).order_by(MachineSession.started_at)
    )).scalars().all()

    guests_map = {g.id: g.name for g in (await db.execute(select(Guest))).scalars().all()}

    total_sessions  = len(sessions)
    total_minutes   = sum(s.duration_min or 0 for s in sessions)
    avg_duration    = round(total_minutes / total_sessions, 1) if total_sessions else 0

    # Wochenweise Gruppierung
    weekly: dict[str, dict] = defaultdict(lambda: {"sessions": 0, "minutes": 0.0})
    for s in sessions:
        week = s.started_at.strftime("%Y-W%W")
        weekly[week]["sessions"] += 1
        weekly[week]["minutes"] += s.duration_min or 0

    # Top-Gäste
    guest_counts: dict[int, dict] = defaultdict(lambda: {"sessions": 0, "minutes": 0.0})
    for s in sessions:
        if s.guest_id:
            guest_counts[s.guest_id]["sessions"] += 1
            guest_counts[s.guest_id]["minutes"] += s.duration_min or 0
    top_guests = sorted(guest_counts.items(), key=lambda x: x[1]["sessions"], reverse=True)[:10]

    return {
        "machine_id":        machine.id,
        "machine_name":      machine.name,
        "period":            {"from": from_date, "to": to_date},
        "total_sessions":    total_sessions,
        "total_hours":       round(total_minutes / 60, 1),
        "avg_duration_min":  avg_duration,
        "lifetime_hours":    round(machine.total_hours or 0, 1),
        "by_week": [
            {"week": w, "sessions": v["sessions"], "hours": round(v["minutes"] / 60, 1)}
            for w, v in sorted(weekly.items())
        ],
        "top_guests": [
            {
                "id": gid,
                "name": guests_map.get(gid, "?"),
                "sessions": v["sessions"],
                "hours": round(v["minutes"] / 60, 1),
            }
            for gid, v in top_guests
        ],
    }


@router.get("/stats/guests/{guest_id}")
async def mcp_get_guest_stats(
    guest_id: int,
    from_date: str | None = Query(None),
    to_date: str | None   = Query(None),
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Aktivitätsprofil eines Gastes: genutzte Maschinen, Stunden, erste/letzte Session."""
    from collections import defaultdict
    guest = (await db.execute(select(Guest).where(Guest.id == guest_id))).scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")

    conditions = [MachineSession.guest_id == guest_id, MachineSession.ended_at.isnot(None)]
    if from_date:
        conditions.append(MachineSession.started_at >= datetime.fromisoformat(from_date))
    if to_date:
        to_dt = datetime.fromisoformat(to_date).replace(hour=23, minute=59, second=59)
        conditions.append(MachineSession.started_at <= to_dt)

    sessions = (await db.execute(
        select(MachineSession).where(and_(*conditions)).order_by(MachineSession.started_at)
    )).scalars().all()

    machines_map = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}

    total_sessions = len(sessions)
    total_minutes  = sum(s.duration_min or 0 for s in sessions)

    # Pro Maschine aggregieren
    machine_data: dict[int, dict] = defaultdict(lambda: {"sessions": 0, "minutes": 0.0, "last_used": None})
    for s in sessions:
        machine_data[s.machine_id]["sessions"] += 1
        machine_data[s.machine_id]["minutes"] += s.duration_min or 0
        machine_data[s.machine_id]["last_used"] = s.started_at.isoformat()

    # Monatliche Aktivität
    monthly: dict[str, int] = defaultdict(int)
    for s in sessions:
        month = s.started_at.strftime("%Y-%m")
        monthly[month] += 1

    return {
        "guest_id":     guest.id,
        "guest_name":   guest.name,
        "period":       {"from": from_date, "to": to_date},
        "total_sessions": total_sessions,
        "total_hours":  round(total_minutes / 60, 1),
        "first_session": sessions[0].started_at.isoformat() if sessions else None,
        "last_session":  sessions[-1].started_at.isoformat() if sessions else None,
        "machines_used": [
            {
                "id":       mid,
                "name":     machines_map.get(mid, "?"),
                "sessions": v["sessions"],
                "hours":    round(v["minutes"] / 60, 1),
                "last_used": v["last_used"],
            }
            for mid, v in sorted(machine_data.items(), key=lambda x: x[1]["sessions"], reverse=True)
        ],
        "by_month": [
            {"month": m, "sessions": c}
            for m, c in sorted(monthly.items())
        ],
    }


# ── Benutzer ───────────────────────────────────────────────────────────────────

@router.get("/users")
async def mcp_list_users(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Alle Lab-Manager-Konten."""
    users = (await db.execute(select(User).order_by(User.name))).scalars().all()
    return [
        {"id": u.id, "name": u.name, "username": u.username, "email": u.email, "role": u.role}
        for u in users
    ]


# ── Gäste Update ───────────────────────────────────────────────────────────────

@router.patch("/guests/{guest_id}")
async def mcp_update_guest(
    guest_id: int, payload: dict,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Gast-Stammdaten bearbeiten (name, email)."""
    guest = (await db.execute(select(Guest).where(Guest.id == guest_id))).scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")
    if "name" in payload:
        guest.name = payload["name"].strip()
    if "email" in payload:
        guest.email = payload["email"].strip() or None
    await db.commit()
    return {"ok": True, "id": guest.id, "name": guest.name, "email": guest.email}


# ── Sessions ───────────────────────────────────────────────────────────────────

@router.post("/sessions/{machine_id}/end")
async def mcp_end_session(
    machine_id: int,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Laufende Session einer Maschine manuell beenden."""
    from app.services.session import end_session
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")
    if not machine.current_guest_id:
        raise HTTPException(409, "Keine aktive Session auf dieser Maschine")
    await end_session(db, machine, ended_by=SessionEndedBy.manager)
    return {"ok": True, "machine": machine.name}


# ── Queue ──────────────────────────────────────────────────────────────────────

@router.get("/queue")
async def mcp_list_queue(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Aktuelle Warteliste (waiting + notified)."""
    entries = (await db.execute(
        select(MachineQueue)
        .where(MachineQueue.status.in_([QueueStatus.waiting, QueueStatus.notified]))
        .order_by(MachineQueue.joined_at)
    )).scalars().all()
    machines_map = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}
    guests_map   = {g.id: g.name for g in (await db.execute(select(Guest))).scalars().all()}
    return [
        {
            "id":          e.id,
            "machine_id":  e.machine_id,
            "machine":     machines_map.get(e.machine_id, "?"),
            "guest_id":    e.guest_id,
            "guest":       guests_map.get(e.guest_id, "?"),
            "status":      e.status,
            "joined_at":   e.joined_at.isoformat(),
            "notified_at": e.notified_at.isoformat() if e.notified_at else None,
        }
        for e in entries
    ]


# ── Automationen ───────────────────────────────────────────────────────────────

@router.get("/automations")
async def mcp_list_automations(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Alle Automationsregeln mit Bedingungen."""
    rules = (await db.execute(select(AutomationRule).order_by(AutomationRule.name))).scalars().all()
    machines_map = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}
    topics_map   = {t.id: t.title for t in (await db.execute(select(NtfyTopic))).scalars().all()}
    result = []
    for r in rules:
        conditions = (await db.execute(
            select(RuleCondition).where(RuleCondition.rule_id == r.id)
        )).scalars().all()
        result.append({
            "id":             r.id,
            "name":           r.name,
            "enabled":        r.enabled,
            "action_type":    r.action_type,
            "target_machine": machines_map.get(r.target_machine_id) if r.target_machine_id else None,
            "off_delay_sec":  r.off_delay_sec,
            "notify_topic":   topics_map.get(r.notify_topic_id) if r.notify_topic_id else None,
            "notify_message": r.notify_message,
            "conditions": [
                {
                    "type":           c.type,
                    "source_machine": machines_map.get(c.source_machine_id) if c.source_machine_id else None,
                    "power_on_w":     c.power_on_w,
                    "power_off_w":    c.power_off_w,
                    "days":           c.days,
                    "time_on":        str(c.time_on) if c.time_on else None,
                    "time_off":       str(c.time_off) if c.time_off else None,
                }
                for c in conditions
            ],
        })
    return result


# ── Plug-Test ──────────────────────────────────────────────────────────────────

@router.post("/plugs/{plug_id}/switch")
async def mcp_test_plug(
    plug_id: int, payload: dict,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Plug schalten (action: 'on' oder 'off'). Funktioniert auch für zugewiesene Plugs."""
    from app.services.plug import switch_plug
    from types import SimpleNamespace
    plug = await db.get(Plug, plug_id)
    if not plug:
        raise HTTPException(404, "Plug nicht gefunden")
    action = payload.get("action", "on")
    if action not in ("on", "off"):
        raise HTTPException(400, "action muss 'on' oder 'off' sein")
    proxy = SimpleNamespace(plug_type=plug.plug_type, plug_ip=plug.plug_ip, plug_token=plug.plug_token)
    ok, msg = await switch_plug(proxy, action)
    return {"ok": ok, "plug": plug.label, "action": action, "message": msg}


# ── Kategorien & Standorte ─────────────────────────────────────────────────────

@router.get("/categories")
async def mcp_list_categories(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Alle Maschinenkategorien."""
    cats = (await db.execute(select(MachineCategory).order_by(MachineCategory.sort_order, MachineCategory.name))).scalars().all()
    return [{"id": c.id, "name": c.name, "icon": c.icon} for c in cats]


@router.get("/locations")
async def mcp_list_locations(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Alle Maschinenstandorte."""
    locs = (await db.execute(select(MachineLocation).order_by(MachineLocation.sort_order, MachineLocation.name))).scalars().all()
    return [{"id": l.id, "name": l.name} for l in locs]


@router.get("/owners")
async def mcp_list_owners(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Alle Maschinen-Eigentümer."""
    owners = (await db.execute(select(MachineOwner).order_by(MachineOwner.sort_order, MachineOwner.name))).scalars().all()
    return [{"id": o.id, "name": o.name} for o in owners]


@router.get("/batteries")
async def mcp_list_batteries(db: AsyncSession = Depends(get_db), _=Depends(require_mcp)):
    """Alle erfassten Akkus."""
    batteries = (await db.execute(select(Battery).order_by(Battery.created_at.desc()))).scalars().all()
    return [{
        "id": b.id,
        "name": b.name,
        "manufacturer": b.manufacturer,
        "model": b.model,
        "serial_number": b.serial_number,
        "purchase_date": b.purchase_date.isoformat() if b.purchase_date else None,
        "value_new": b.value_new,
        "status": b.status,
        "comment": b.comment,
    } for b in batteries]


# ── Gast-Details ───────────────────────────────────────────────────────────────

@router.get("/guests/{guest_id}")
async def mcp_get_guest(
    guest_id: int,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Einzelner Gast mit Berechtigungen und letzter Aktivität."""
    guest = (await db.execute(select(Guest).where(Guest.id == guest_id))).scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")
    perms = (await db.execute(
        select(Permission).where(Permission.guest_id == guest_id)
    )).scalars().all()
    machines_map = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}
    last_log = (await db.execute(
        select(ActivityLog)
        .where(ActivityLog.guest_id == guest_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    last_session = (await db.execute(
        select(MachineSession)
        .where(MachineSession.guest_id == guest_id)
        .order_by(MachineSession.started_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return {
        "id":               guest.id,
        "name":             guest.name,
        "username":         guest.username,
        "email":            guest.email,
        "is_active":        guest.is_active,
        "is_blocked":       guest.is_blocked,
        "pending_approval": guest.pending_approval,
        "created_at":       guest.created_at.isoformat(),
        "permissions": [
            {
                "machine_id":   p.machine_id,
                "machine_name": machines_map.get(p.machine_id, "?"),
                "is_blocked":   p.is_blocked,
            }
            for p in perms
        ],
        "last_activity":  last_log.created_at.isoformat() if last_log else None,
        "last_session": {
            "machine":    machines_map.get(last_session.machine_id, "?"),
            "started_at": last_session.started_at.isoformat(),
            "ended_at":   last_session.ended_at.isoformat() if last_session.ended_at else None,
        } if last_session else None,
    }
