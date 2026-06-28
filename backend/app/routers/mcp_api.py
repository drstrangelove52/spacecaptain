"""Interne API-Endpunkte für den MCP-Server. Auth via X-MCP-Key Header (DB-Token)."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timezone

from app.database import get_db
from app.models import (Machine, Guest, ActivityLog, MaintenanceInterval,
                         MaintenanceRecord, EmergencyState, MachineQueue, QueueStatus, User,
                         Permission, NtfyTopic)
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

@router.patch("/machines/{machine_id}/status")
async def mcp_set_machine_status(
    machine_id: int, payload: dict,
    db: AsyncSession = Depends(get_db), _=Depends(require_mcp),
):
    """Maschinenstatus setzen: online | offline | maintenance."""
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
