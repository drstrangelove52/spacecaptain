"""
Export / Import — Konfiguration + Logs
Passwort-Hashes werden mitexportiert — Backup-Datei sicher aufbewahren!
"""
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import (
    User, Guest, Machine, Permission,
    ActivityLog, MachineSession, LogType, SessionEndedBy,
    MaintenanceInterval, MaintenanceRecord, SystemSettings, Announcement,
)
from app.services.auth import require_admin
from app.services.system_settings import get_system_settings

router = APIRouter(prefix="/backup", tags=["backup"])


def _iso(dt):
    return dt.isoformat() if dt else None


@router.get("/export")
async def export_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    cfg        = await get_system_settings(db)
    users      = (await db.execute(select(User))).scalars().all()
    guests     = (await db.execute(select(Guest))).scalars().all()
    machines   = (await db.execute(select(Machine))).scalars().all()
    perms      = (await db.execute(select(Permission))).scalars().all()
    logs       = (await db.execute(select(ActivityLog).order_by(ActivityLog.id))).scalars().all()
    sessions   = (await db.execute(select(MachineSession).order_by(MachineSession.id))).scalars().all()
    maint_ivs  = (await db.execute(select(MaintenanceInterval).order_by(MaintenanceInterval.id))).scalars().all()
    maint_recs = (await db.execute(select(MaintenanceRecord).order_by(MaintenanceRecord.id))).scalars().all()
    announcements = (await db.execute(select(Announcement).order_by(Announcement.id))).scalars().all()

    # Stabile Referenzen statt IDs
    guest_by_id   = {g.id: g.username  for g in guests}
    machine_by_id = {m.id: m.qr_token  for m in machines}
    user_by_id    = {u.id: u.email     for u in users}

    return {
        "version": "2.5",
        "exported_at": datetime.utcnow().isoformat(),
        "settings": {
            "nfc_writer_url":          cfg.nfc_writer_url,
            "jwt_expire_minutes":      cfg.jwt_expire_minutes,
            "guest_token_days":        cfg.guest_token_days,
            "modal_backdrop_input":    cfg.modal_backdrop_input,
            "modal_backdrop_display":  cfg.modal_backdrop_display,
            "queue_reservation_minutes": cfg.queue_reservation_minutes,
            "display_refresh_seconds":   cfg.display_refresh_seconds,
            "display_page_size":         cfg.display_page_size,
            "dashboard_refresh_seconds": cfg.dashboard_refresh_seconds,
            "ticker_text":               cfg.ticker_text,
            "ticker_speed":            cfg.ticker_speed,
            "ticker_font_size":        cfg.ticker_font_size,
            "announcement":            cfg.announcement,
            "announcement_font_size":  cfg.announcement_font_size,
        },
        "users": [{
            "name": u.name, "email": u.email, "role": u.role,
            "phone": u.phone, "area": u.area, "is_active": u.is_active,
            "password_hash": u.password_hash,
        } for u in users],
        "guests": [{
            "name": g.name, "username": g.username, "email": g.email,
            "phone": g.phone, "note": g.note, "is_active": g.is_active,
            "password_hash": g.password_hash,
        } for g in guests],
        "machines": [{
            "name": m.name, "category": m.category, "manufacturer": m.manufacturer,
            "model": m.model, "location": m.location, "status": m.status,
            "plug_type": m.plug_type, "plug_ip": m.plug_ip, "plug_extra": m.plug_extra,
            "plug_token": m.plug_token, "idle_power_w": m.idle_power_w,
            "idle_timeout_min": m.idle_timeout_min, "plug_poll_interval_sec": m.plug_poll_interval_sec,
            "training_required": m.training_required, "total_hours": m.total_hours,
            "comment": m.comment, "qr_token": m.qr_token,
        } for m in machines],
        "permissions": [{
            "guest_username":    guest_by_id.get(p.guest_id),
            "machine_qr_token": machine_by_id.get(p.machine_id),
            "is_blocked":        p.is_blocked,
        } for p in perms if guest_by_id.get(p.guest_id) and machine_by_id.get(p.machine_id)],
        "sessions": [{
            "machine_qr_token": machine_by_id.get(s.machine_id),
            "guest_username":   guest_by_id.get(s.guest_id),
            "started_at":       _iso(s.started_at),
            "ended_at":         _iso(s.ended_at),
            "duration_min":     s.duration_min,
            "energy_wh":        s.energy_wh,
            "ended_by":         s.ended_by,
        } for s in sessions if machine_by_id.get(s.machine_id)],
        "maintenance_intervals": [{
            "machine_qr_token":  machine_by_id.get(iv.machine_id),
            "name":              iv.name,
            "description":       iv.description,
            "interval_hours":    iv.interval_hours,
            "interval_days":     iv.interval_days,
            "warning_hours":     iv.warning_hours,
            "warning_days":      iv.warning_days,
            "is_active":         iv.is_active,
            "created_at":        _iso(iv.created_at),
            "_export_id":        iv.id,
        } for iv in maint_ivs if machine_by_id.get(iv.machine_id)],
        "maintenance_records": [{
            "interval_export_id":  r.interval_id,
            "name":                r.name,
            "machine_qr_token":    machine_by_id.get(r.machine_id),
            "user_email":          user_by_id.get(r.performed_by),
            "performed_at":        _iso(r.performed_at),
            "hours_at_execution":  r.hours_at_execution,
            "notes":               r.notes,
        } for r in maint_recs if machine_by_id.get(r.machine_id)],
        "announcements": [{
            "text":               a.text,
            "is_active":          a.is_active,
            "is_recurring":       a.is_recurring,
            "display_type":       a.display_type or "banner",
            "start_at":           _iso(a.start_at),
            "end_at":             _iso(a.end_at),
            "recur_days":         a.recur_days,
            "recur_start_time":   a.recur_start_time.strftime("%H:%M") if a.recur_start_time else None,
            "recur_end_time":     a.recur_end_time.strftime("%H:%M") if a.recur_end_time else None,
            "recur_valid_from":   a.recur_valid_from.isoformat() if a.recur_valid_from else None,
            "recur_valid_until":  a.recur_valid_until.isoformat() if a.recur_valid_until else None,
            "created_at":         _iso(a.created_at),
        } for a in announcements],
        "activity_log": [{
            "type":             l.type,
            "message":          l.message,
            "meta":             l.meta,
            "created_at":       _iso(l.created_at),
            "guest_username":   guest_by_id.get(l.guest_id),
            "machine_qr_token": machine_by_id.get(l.machine_id),
            "user_email":       user_by_id.get(l.user_id),
        } for l in logs],
    }


@router.post("/import")
async def import_config(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    stats = {"users": 0, "guests": 0, "machines": 0, "permissions": 0,
             "sessions": 0, "activity_log": 0,
             "maintenance_intervals": 0, "maintenance_records": 0, "skipped": 0}

    # ── Systemeinstellungen ────────────────────────────────
    if s := payload.get("settings"):
        cfg = await get_system_settings(db)
        for field in ("nfc_writer_url", "jwt_expire_minutes", "guest_token_days",
                      "modal_backdrop_input", "modal_backdrop_display",
                      "queue_reservation_minutes", "display_refresh_seconds",
                      "display_page_size", "dashboard_refresh_seconds",
                      "ticker_text", "ticker_speed", "ticker_font_size",
                      "announcement", "announcement_font_size"):
            if field in s:
                setattr(cfg, field, s[field])
        await db.flush()

    # ── Benutzer ──────────────────────────────────────────
    existing_emails = {u.email for u in (await db.execute(select(User))).scalars().all()}
    for u in payload.get("users", []):
        if u.get("email") in existing_emails:
            stats["skipped"] += 1; continue
        db.add(User(
            name=u["name"], email=u["email"], role=u.get("role", "manager"),
            phone=u.get("phone"), area=u.get("area"), is_active=u.get("is_active", True),
            password_hash=u["password_hash"],
        ))
        stats["users"] += 1

    # ── Gäste ─────────────────────────────────────────────
    existing_usernames = {g.username for g in (await db.execute(select(Guest))).scalars().all()}
    for g in payload.get("guests", []):
        if g.get("username") in existing_usernames:
            stats["skipped"] += 1; continue
        db.add(Guest(
            name=g["name"], username=g["username"], email=g.get("email"),
            phone=g.get("phone"), note=g.get("note"), is_active=g.get("is_active", True),
            password_hash=g.get("password_hash"),
        ))
        stats["guests"] += 1

    await db.flush()

    # ── Maschinen ─────────────────────────────────────────
    existing_tokens = {m.qr_token for m in (await db.execute(select(Machine))).scalars().all()}
    for m in payload.get("machines", []):
        if m.get("qr_token") in existing_tokens:
            stats["skipped"] += 1; continue
        db.add(Machine(
            name=m["name"], category=m.get("category", "Sonstiges"),
            manufacturer=m.get("manufacturer"), model=m.get("model"),
            location=m.get("location"), status=m.get("status", "online"),
            plug_type=m.get("plug_type", "none"), plug_ip=m.get("plug_ip"),
            plug_extra=m.get("plug_extra"), plug_token=m.get("plug_token"),
            idle_power_w=m.get("idle_power_w"), idle_timeout_min=m.get("idle_timeout_min"),
            comment=m.get("comment"), qr_token=m["qr_token"],
        ))
        stats["machines"] += 1

    await db.flush()

    # Lookup-Maps mit aktuellen IDs (inkl. neu importierter Einträge)
    guest_map   = {g.username: g.id  for g in (await db.execute(select(Guest))).scalars().all()}
    machine_map = {m.qr_token: m.id  for m in (await db.execute(select(Machine))).scalars().all()}
    user_map    = {u.email:    u.id  for u in (await db.execute(select(User))).scalars().all()}

    # ── Berechtigungen ────────────────────────────────────
    existing_perms = {
        (p.guest_id, p.machine_id)
        for p in (await db.execute(select(Permission))).scalars().all()
    }
    for p in payload.get("permissions", []):
        gid = guest_map.get(p.get("guest_username"))
        mid = machine_map.get(p.get("machine_qr_token"))
        if not gid or not mid or (gid, mid) in existing_perms:
            stats["skipped"] += 1; continue
        db.add(Permission(guest_id=gid, machine_id=mid, is_blocked=p.get("is_blocked", False)))
        stats["permissions"] += 1

    # ── Sessions ──────────────────────────────────────────
    # Gleichzeitig total_hours pro Maschine akkumulieren (für v2.11-Backups ohne total_hours)
    hours_accumulator: dict[int, float] = {}
    for s in payload.get("sessions", []):
        mid = machine_map.get(s.get("machine_qr_token"))
        if not mid:
            stats["skipped"] += 1; continue
        db.add(MachineSession(
            machine_id=mid,
            guest_id=guest_map.get(s.get("guest_username")),
            started_at=datetime.fromisoformat(s["started_at"]) if s.get("started_at") else datetime.utcnow(),
            ended_at=datetime.fromisoformat(s["ended_at"]) if s.get("ended_at") else None,
            duration_min=s.get("duration_min"),
            energy_wh=s.get("energy_wh"),
            ended_by=s.get("ended_by"),
        ))
        if s.get("duration_min"):
            hours_accumulator[mid] = hours_accumulator.get(mid, 0.0) + s["duration_min"] / 60.0
        stats["sessions"] += 1

    # total_hours aus Sessions zurückrechnen (greift wenn Backup kein total_hours kennt)
    await db.flush()
    for mid, hours in hours_accumulator.items():
        result = await db.execute(select(Machine).where(Machine.id == mid))
        m = result.scalar_one_or_none()
        if m and m.total_hours == 0.0:
            m.total_hours = round(hours, 4)

    # ── Wartungsintervalle ────────────────────────────────
    # Bestehende Intervalle laden (name + machine_id als Schlüssel)
    existing_intervals = (await db.execute(select(MaintenanceInterval))).scalars().all()
    existing_iv_keys = {(iv.machine_id, iv.name) for iv in existing_intervals}
    # Map: export_id → neue oder bestehende DB-id
    interval_id_map: dict[int, int] = {}
    # Bestehende Intervalle ebenfalls in die Map aufnehmen (für Records)
    for iv in existing_intervals:
        for ex_iv in payload.get("maintenance_intervals", []):
            ex_mid = machine_map.get(ex_iv.get("machine_qr_token"))
            if ex_mid == iv.machine_id and ex_iv.get("name") == iv.name and ex_iv.get("_export_id"):
                interval_id_map[ex_iv["_export_id"]] = iv.id

    for iv in payload.get("maintenance_intervals", []):
        mid = machine_map.get(iv.get("machine_qr_token"))
        if not mid:
            stats["skipped"] += 1; continue
        if (mid, iv["name"]) in existing_iv_keys:
            stats["skipped"] += 1; continue
        new_iv = MaintenanceInterval(
            machine_id=mid,
            name=iv["name"],
            description=iv.get("description"),
            interval_hours=iv.get("interval_hours"),
            interval_days=iv.get("interval_days"),
            warning_hours=iv.get("warning_hours"),
            warning_days=iv.get("warning_days"),
            is_active=iv.get("is_active", True),
            created_at=datetime.fromisoformat(iv["created_at"]) if iv.get("created_at") else datetime.utcnow(),
        )
        db.add(new_iv)
        await db.flush()
        await db.refresh(new_iv)
        existing_iv_keys.add((mid, iv["name"]))
        if iv.get("_export_id"):
            interval_id_map[iv["_export_id"]] = new_iv.id
        stats["maintenance_intervals"] += 1

    # ── Wartungsausführungen ──────────────────────────────
    # Bestehende Records laden (interval_id + performed_at als Schlüssel)
    existing_records = (await db.execute(select(MaintenanceRecord))).scalars().all()
    existing_rec_keys = {(r.interval_id, r.performed_at.isoformat() if r.performed_at else "") for r in existing_records}

    for r in payload.get("maintenance_records", []):
        export_iv_id = r.get("interval_export_id")
        new_iv_id = interval_id_map.get(export_iv_id) if export_iv_id else None
        mid = machine_map.get(r.get("machine_qr_token"))
        if not mid:
            stats["skipped"] += 1; continue
        performed_at = datetime.fromisoformat(r["performed_at"]) if r.get("performed_at") else datetime.utcnow()
        rec_key = (new_iv_id, performed_at.isoformat())
        if rec_key in existing_rec_keys:
            stats["skipped"] += 1; continue
        existing_rec_keys.add(rec_key)
        db.add(MaintenanceRecord(
            interval_id=new_iv_id,
            name=r.get("name"),
            machine_id=mid,
            performed_by=user_map.get(r.get("user_email")),
            performed_at=performed_at,
            hours_at_execution=r.get("hours_at_execution"),
            notes=r.get("notes"),
        ))
        stats["maintenance_records"] += 1

    # ── Mitteilungen ──────────────────────────────────────
    existing_ann = {
        (a.text, _iso(a.start_at), a.recur_days)
        for a in (await db.execute(select(Announcement))).scalars().all()
    }
    for a in payload.get("announcements", []):
        from datetime import time as _time, date as _date
        start_at = datetime.fromisoformat(a["start_at"]) if a.get("start_at") else None
        key = (a["text"], _iso(start_at), a.get("recur_days"))
        if key in existing_ann:
            stats["skipped"] += 1; continue
        existing_ann.add(key)
        def _parse_time(s):
            if not s: return None
            h, m = s.split(":")
            return _time(int(h), int(m))
        db.add(Announcement(
            text=a["text"],
            is_active=a.get("is_active", True),
            is_recurring=a.get("is_recurring", False),
            display_type=a.get("display_type", "banner"),
            start_at=start_at,
            end_at=datetime.fromisoformat(a["end_at"]) if a.get("end_at") else None,
            recur_days=a.get("recur_days"),
            recur_start_time=_parse_time(a.get("recur_start_time")),
            recur_end_time=_parse_time(a.get("recur_end_time")),
            recur_valid_from=_date.fromisoformat(a["recur_valid_from"]) if a.get("recur_valid_from") else None,
            recur_valid_until=_date.fromisoformat(a["recur_valid_until"]) if a.get("recur_valid_until") else None,
            created_at=datetime.fromisoformat(a["created_at"]) if a.get("created_at") else datetime.utcnow(),
        ))
        if "announcements" not in stats:
            stats["announcements"] = 0
        stats["announcements"] += 1

    # ── Activity Log ──────────────────────────────────────
    for l in payload.get("activity_log", []):
        db.add(ActivityLog(
            type=l["type"],
            message=l["message"],
            meta=l.get("meta"),
            created_at=datetime.fromisoformat(l["created_at"]) if l.get("created_at") else datetime.utcnow(),
            guest_id=guest_map.get(l.get("guest_username")),
            machine_id=machine_map.get(l.get("machine_qr_token")),
            user_id=user_map.get(l.get("user_email")),
        ))
        stats["activity_log"] += 1

    await db.commit()
    return {"ok": True, "imported": stats}
