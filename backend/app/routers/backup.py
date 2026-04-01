"""
Export / Import — Konfiguration + Logs
Passwort-Hashes werden mitexportiert — Backup-Datei sicher aufbewahren!
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, inspect

from app.database import get_db
from app.models import (
    User, Guest, Machine, Permission,
    ActivityLog, MachineSession, LogType, SessionEndedBy,
    MaintenanceInterval, MaintenanceRecord, SystemSettings, Announcement, NtfyTopic,
)
from app.services.auth import require_admin
from app.services.system_settings import get_system_settings
from app.services.backup_service import BACKUP_DIR, _list_backup_files
from app.services.logger import log as activity_log
from app.config import APP_VERSION

router = APIRouter(prefix="/backup", tags=["backup"])


def _validate_filename(filename: str) -> None:
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Ungültiger Dateiname")


def _iso(dt):
    return dt.isoformat() if dt else None


async def _build_export_data(db: AsyncSession) -> dict:
    """Erstellt die Export-Datenstruktur (wird von Export-Endpoint und Auto-Backup genutzt)."""
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
    ntfy_topics   = (await db.execute(select(NtfyTopic).order_by(NtfyTopic.id))).scalars().all()

    # Stabile Referenzen statt IDs
    guest_by_id   = {g.id: g.username  for g in guests}
    machine_by_id = {m.id: m.qr_token  for m in machines}
    user_by_id    = {u.id: u.email     for u in users}

    return {
        "version": "2.6",
        "app_version": APP_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "settings": {
            col.key: getattr(cfg, col.key)
            for col in inspect(SystemSettings).mapper.column_attrs
            if col.key != "id"
        },
        "ntfy_topics": [{
            "key":         t.key,
            "topic":       t.topic,
            "title":       t.title,
            "description": t.description,
        } for t in ntfy_topics],
        "users": [{
            "name": u.name, "email": u.email, "role": u.role,
            "phone": u.phone, "area": u.area, "is_active": u.is_active,
            "password_hash": u.password_hash,
        } for u in users],
        "guests": [{
            "name": g.name, "username": g.username, "email": g.email,
            "phone": g.phone, "note": g.note, "is_active": g.is_active,
            "password_hash": g.password_hash, "ntfy_topic": g.ntfy_topic,
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


@router.get("/export")
async def export_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    data = await _build_export_data(db)
    await activity_log(db, LogType.backup_exported,
                       "Backup manuell exportiert", user_id=current_user.id)
    return data


@router.get("/files")
async def list_backup_files(
    _: User = Depends(require_admin),
):
    files_with_stat = [(f, f.stat()) for f in reversed(_list_backup_files())]
    return [
        {
            "filename": f.name,
            "size_bytes": st.st_size,
            "created_at": datetime.utcfromtimestamp(st.st_mtime).isoformat(),
        }
        for f, st in files_with_stat
    ]


@router.get("/files/{filename}")
async def download_backup_file(
    filename: str,
    _: User = Depends(require_admin),
):
    _validate_filename(filename)
    path = BACKUP_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    return FileResponse(path, media_type="application/json", filename=filename)


@router.delete("/files/{filename}")
async def delete_backup_file(
    filename: str,
    _: User = Depends(require_admin),
):
    _validate_filename(filename)
    path = BACKUP_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    path.unlink()
    return {"ok": True}


@router.post("/files/create")
async def create_backup_now(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Erstellt sofort ein Backup (manuell ausgelöst)."""
    from app.services.backup_service import _create_backup, _cleanup_old_backups
    cfg = await get_system_settings(db)
    path = await _create_backup(db)
    _cleanup_old_backups(cfg.auto_backup_keep)
    await activity_log(db, LogType.backup_exported,
                       f"Backup manuell erstellt: {path.name}", user_id=current_user.id)
    return {"ok": True, "filename": path.name}


@router.post("/files/{filename}/restore")
async def restore_from_file(
    filename: str,
    overwrite: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Startet einen Restore direkt aus einer gespeicherten Backup-Datei."""
    _validate_filename(filename)
    path = BACKUP_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    import json as _json
    payload = _json.loads(path.read_text(encoding="utf-8"))
    result = await _do_import(payload, db, overwrite=overwrite, source_filename=filename)
    await activity_log(db, LogType.backup_imported,
                       f"Backup wiederhergestellt: {filename}", user_id=current_user.id)
    return result


async def _do_import(payload: dict, db: AsyncSession, overwrite: bool = False, source_filename: str = "Backup") -> dict:
    # KOMPATIBILITÄTSREGEL — Backups älterer Versionen müssen immer importierbar bleiben:
    #   • Neue Settings-Felder: einfach zur Feldliste hinzufügen — der `if field in s`-Guard
    #     überspringt sie automatisch wenn sie im Backup fehlen.
    #   • Neue Top-Level-Sektionen: immer payload.get("sektion", []) verwenden, nie payload["sektion"].
    #   • Neue Felder innerhalb von Datensätzen: immer a.get("feld", default) verwenden, nie a["feld"].
    #   • Felder umbenennen: Altnamen als Fallback lesen, z.B. a.get("neu") or a.get("alt").
    #   • Niemals breaking changes ohne Versions-Prüfung (payload.get("version")) einbauen.
    backup_version = payload.get("version", "unbekannt")

    stats = {"users": 0, "guests": 0, "machines": 0, "permissions": 0,
             "sessions": 0, "activity_log": 0, "announcements": 0, "ntfy_topics": 0,
             "maintenance_intervals": 0, "maintenance_records": 0, "skipped": 0, "updated": 0}

    # ── Systemeinstellungen ────────────────────────────────
    if s := payload.get("settings"):
        cfg = await get_system_settings(db)
        valid_fields = {col.key for col in inspect(SystemSettings).mapper.column_attrs if col.key != "id"}
        for field, value in s.items():
            if field in valid_fields:
                setattr(cfg, field, value)
        await db.flush()

    # ── Benutzer ──────────────────────────────────────────
    existing_users = {u.email: u for u in (await db.execute(select(User))).scalars().all()}
    for u in payload.get("users", []):
        if u.get("email") in existing_users:
            if overwrite:
                row = existing_users[u["email"]]
                row.name = u["name"]; row.role = u.get("role", row.role)
                row.phone = u.get("phone"); row.area = u.get("area")
                row.is_active = u.get("is_active", row.is_active)
                row.password_hash = u.get("password_hash", row.password_hash)
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
            continue
        db.add(User(
            name=u["name"], email=u["email"], role=u.get("role", "manager"),
            phone=u.get("phone"), area=u.get("area"), is_active=u.get("is_active", True),
            password_hash=u["password_hash"],
        ))
        stats["users"] += 1

    # ── Gäste ─────────────────────────────────────────────
    existing_guests = {g.username: g for g in (await db.execute(select(Guest))).scalars().all()}
    for g in payload.get("guests", []):
        if g.get("username") in existing_guests:
            if overwrite:
                row = existing_guests[g["username"]]
                row.name = g["name"]; row.email = g.get("email")
                row.phone = g.get("phone"); row.note = g.get("note")
                row.is_active = g.get("is_active", row.is_active)
                row.password_hash = g.get("password_hash", row.password_hash)
                row.ntfy_topic = g.get("ntfy_topic", row.ntfy_topic)
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
            continue
        db.add(Guest(
            name=g["name"], username=g["username"], email=g.get("email"),
            phone=g.get("phone"), note=g.get("note"), is_active=g.get("is_active", True),
            password_hash=g.get("password_hash"),
            ntfy_topic=g.get("ntfy_topic"),
        ))
        stats["guests"] += 1

    await db.flush()

    # ── Maschinen ─────────────────────────────────────────
    existing_machines = {m.qr_token: m for m in (await db.execute(select(Machine))).scalars().all()}
    for m in payload.get("machines", []):
        if m.get("qr_token") in existing_machines:
            if overwrite:
                row = existing_machines[m["qr_token"]]
                row.name = m["name"]; row.category = m.get("category", row.category)
                row.manufacturer = m.get("manufacturer"); row.model = m.get("model")
                row.location = m.get("location"); row.status = m.get("status", row.status)
                row.plug_type = m.get("plug_type", row.plug_type); row.plug_ip = m.get("plug_ip")
                row.plug_extra = m.get("plug_extra"); row.plug_token = m.get("plug_token")
                row.idle_power_w = m.get("idle_power_w"); row.idle_timeout_min = m.get("idle_timeout_min")
                row.training_required = m.get("training_required", row.training_required)
                row.comment = m.get("comment")
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
            continue
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
    existing_perms_map = {
        (p.guest_id, p.machine_id): p
        for p in (await db.execute(select(Permission))).scalars().all()
    }
    for p in payload.get("permissions", []):
        gid = guest_map.get(p.get("guest_username"))
        mid = machine_map.get(p.get("machine_qr_token"))
        if not gid or not mid:
            stats["skipped"] += 1; continue
        restored_blocked = p.get("is_blocked", False)
        if (gid, mid) in existing_perms_map:
            if overwrite:
                row = existing_perms_map[(gid, mid)]
                old_blocked = row.is_blocked
                row.is_blocked = restored_blocked
                stats["updated"] += 1
                if old_blocked != restored_blocked:
                    log_type = LogType.permission_revoked if restored_blocked else LogType.permission_granted
                    db.add(ActivityLog(
                        type=log_type,
                        message=f"Berechtigung wiederhergestellt aus {source_filename}",
                        meta={"comment": f"Wiederhergestellt aus {source_filename}"},
                        guest_id=gid,
                        machine_id=mid,
                    ))
            else:
                stats["skipped"] += 1
            continue
        db.add(Permission(guest_id=gid, machine_id=mid, is_blocked=restored_blocked))
        stats["permissions"] += 1

    # ── Sessions ──────────────────────────────────────────
    existing_sessions = {
        (sess.machine_id, sess.started_at.isoformat() if sess.started_at else "")
        for sess in (await db.execute(select(MachineSession))).scalars().all()
    }
    # Gleichzeitig total_hours pro Maschine akkumulieren (für v2.11-Backups ohne total_hours)
    hours_accumulator: dict[int, float] = {}
    for s in payload.get("sessions", []):
        mid = machine_map.get(s.get("machine_qr_token"))
        if not mid:
            stats["skipped"] += 1; continue
        started_at = datetime.fromisoformat(s["started_at"]) if s.get("started_at") else None
        sess_key = (mid, started_at.isoformat() if started_at else "")
        if sess_key in existing_sessions:
            stats["skipped"] += 1; continue
        existing_sessions.add(sess_key)
        db.add(MachineSession(
            machine_id=mid,
            guest_id=guest_map.get(s.get("guest_username")),
            started_at=started_at or datetime.utcnow(),
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
    existing_iv_map = {(iv.machine_id, iv.name): iv for iv in existing_intervals}
    existing_iv_keys = set(existing_iv_map.keys())
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
            if overwrite:
                existing_iv = existing_iv_map.get((mid, iv["name"]))
                if existing_iv:
                    existing_iv.description = iv.get("description")
                    existing_iv.interval_hours = iv.get("interval_hours")
                    existing_iv.interval_days = iv.get("interval_days")
                    existing_iv.warning_hours = iv.get("warning_hours")
                    existing_iv.warning_days = iv.get("warning_days")
                    existing_iv.is_active = iv.get("is_active", existing_iv.is_active)
                    if iv.get("_export_id"):
                        interval_id_map[iv["_export_id"]] = existing_iv.id
                    stats["updated"] += 1
            else:
                stats["skipped"] += 1
            continue
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
        stats["announcements"] += 1

    # ── ntfy Topics ───────────────────────────────────────
    existing_topics = {t.key: t for t in (await db.execute(select(NtfyTopic))).scalars().all()}
    for t in payload.get("ntfy_topics", []):
        if t.get("key") in existing_topics:
            if overwrite:
                row = existing_topics[t["key"]]
                row.topic = t["topic"]; row.title = t["title"]
                row.description = t.get("description")
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
            continue
        db.add(NtfyTopic(
            key=t["key"], topic=t["topic"],
            title=t["title"], description=t.get("description"),
        ))
        stats["ntfy_topics"] += 1

    # ── Activity Log ──────────────────────────────────────
    existing_logs = {
        (e.type, e.message, e.created_at.isoformat() if e.created_at else "", e.guest_id, e.machine_id)
        for e in (await db.execute(select(ActivityLog))).scalars().all()
    }
    for l in payload.get("activity_log", []):
        created_at = datetime.fromisoformat(l["created_at"]) if l.get("created_at") else datetime.utcnow()
        gid = guest_map.get(l.get("guest_username"))
        mid = machine_map.get(l.get("machine_qr_token"))
        log_key = (l["type"], l["message"], created_at.isoformat(), gid, mid)
        if log_key in existing_logs:
            stats["skipped"] += 1; continue
        existing_logs.add(log_key)
        db.add(ActivityLog(
            type=l["type"],
            message=l["message"],
            meta=l.get("meta"),
            created_at=created_at,
            guest_id=gid,
            machine_id=mid,
            user_id=user_map.get(l.get("user_email")),
        ))
        stats["activity_log"] += 1

    await db.commit()
    return {"ok": True, "imported": stats, "backup_version": backup_version}


@router.post("/import")
async def import_config(
    payload: dict,
    overwrite: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await _do_import(payload, db, overwrite=overwrite)
    await activity_log(db, LogType.backup_imported,
                       "Backup importiert (Upload)", user_id=current_user.id)
    return result
