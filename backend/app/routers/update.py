import io
import json
import platform
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import APP_VERSION, BUILD_NR
from app.database import get_db
from app.models import (
    ActivityLog, Guest, Machine, MachineSession,
    Permission, SystemSettings, User,
)
from app.services.auth import require_admin

router = APIRouter(prefix="/update", tags=["update"])

TRIGGER_DIR = Path("/app/update_trigger")
TRIGGER_FILE = TRIGGER_DIR / "trigger"
RESTART_FILE = TRIGGER_DIR / "restart"
LOG_FILE = TRIGGER_DIR / "update.log"
STATUS_FILE = TRIGGER_DIR / "update.status"
HEARTBEAT_FILE = TRIGGER_DIR / "watcher_heartbeat"


@router.get("/status")
async def get_update_status(_: User = Depends(require_admin)):
    watcher_ready = (
        HEARTBEAT_FILE.exists()
        and (datetime.now().timestamp() - HEARTBEAT_FILE.stat().st_mtime) < 30
    )
    last_triggered = None
    if LOG_FILE.exists():
        last_triggered = datetime.fromtimestamp(LOG_FILE.stat().st_mtime).isoformat()
    last_result = STATUS_FILE.read_text().strip() if STATUS_FILE.exists() else None
    return {
        "version": APP_VERSION,
        "build": BUILD_NR,
        "pending": TRIGGER_FILE.exists() or RESTART_FILE.exists(),
        "watcher_ready": watcher_ready,
        "volume_mounted": TRIGGER_DIR.exists(),
        "last_triggered": last_triggered,
        "last_result": last_result,
    }


def _check_watcher_ready():
    if not TRIGGER_DIR.exists():
        raise HTTPException(
            status_code=503,
            detail="Update-Verzeichnis nicht gemountet — Update-Watcher nicht eingerichtet"
        )
    if TRIGGER_FILE.exists() or RESTART_FILE.exists():
        raise HTTPException(status_code=409, detail="Vorgang läuft bereits")


@router.post("/trigger")
async def trigger_update(_: User = Depends(require_admin)):
    _check_watcher_ready()
    TRIGGER_FILE.write_text(datetime.now().isoformat())
    return {"status": "triggered"}


@router.post("/restart")
async def trigger_restart(_: User = Depends(require_admin)):
    _check_watcher_ready()
    RESTART_FILE.write_text(datetime.now().isoformat())
    return {"status": "restart_triggered"}


@router.get("/log-bundle")
async def download_log_bundle(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    buf = io.BytesIO()
    now = datetime.now()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        # README
        zf.writestr("README.txt", (
            f"SpaceCaptain Log Bundle\n"
            f"Erstellt: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Version:  {APP_VERSION}  Build: {BUILD_NR or '—'}\n\n"
            "Inhalt:\n"
            "  system_info.json  — Versionsinformationen und Laufzeitumgebung\n"
            "  settings.json     — Systemkonfiguration (Tokens/Passwörter entfernt)\n"
            "  db_overview.json  — Datenbankübersicht (Anzahl Einträge pro Tabelle)\n"
            "  active_sessions.json — Aktive Maschinensessions\n"
            "  activity_log.json — Letzte 200 Aktivitätslog-Einträge\n"
            "  update.log        — Update-Watcher-Log (falls vorhanden)\n"
        ))

        # System-Info
        uptime_sec = None
        try:
            uptime_sec = float(Path("/proc/uptime").read_text().split()[0])
        except Exception:
            pass

        system_info = {
            "spacecaptain_version": APP_VERSION,
            "build_nr": BUILD_NR or None,
            "generated_at": now.isoformat(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "container_uptime_seconds": uptime_sec,
            "watcher_ready": TRIGGER_DIR.exists(),
            "update_status": STATUS_FILE.read_text().strip() if STATUS_FILE.exists() else None,
        }
        zf.writestr("system_info.json", json.dumps(system_info, indent=2, default=str))

        # Settings (anonymisiert)
        s = await db.scalar(select(SystemSettings))
        if s:
            settings_data = {
                "space_name": s.space_name,
                "room_open": s.room_open,
                "room_open_auto": s.room_open_auto,
                "jwt_expire_minutes": s.jwt_expire_minutes,
                "queue_reservation_minutes": s.queue_reservation_minutes,
                "display_refresh_seconds": s.display_refresh_seconds,
                "display_page_size": s.display_page_size,
                "dashboard_refresh_seconds": s.dashboard_refresh_seconds,
                "ntfy_server": s.ntfy_server,
                "ntfy_token": "***" if s.ntfy_token else None,
                "emergency_trigger_token": "***" if s.emergency_trigger_token else None,
                "emergency_duration_sec": s.emergency_duration_sec,
                "auto_backup_enabled": s.auto_backup_enabled,
                "auto_backup_hour": s.auto_backup_hour,
                "auto_backup_minute": s.auto_backup_minute,
                "auto_backup_keep": s.auto_backup_keep,
            }
            zf.writestr("settings.json", json.dumps(settings_data, indent=2, default=str))

        # DB-Übersicht
        tables = ["guests", "users", "machines", "permissions", "machine_sessions",
                  "activity_log", "plugs", "ntfy_topics", "automation_rules",
                  "maintenance_intervals", "announcements"]
        counts = {}
        for table in tables:
            try:
                result = await db.scalar(text(f"SELECT COUNT(*) FROM `{table}`"))
                counts[table] = result
            except Exception:
                counts[table] = "error"

        active_count = await db.scalar(
            select(func.count()).where(MachineSession.ended_at.is_(None))
        )
        counts["active_sessions"] = active_count
        zf.writestr("db_overview.json", json.dumps(counts, indent=2))

        # Aktive Sessions
        active_rows = (await db.execute(
            select(MachineSession)
            .where(MachineSession.ended_at.is_(None))
            .order_by(MachineSession.started_at.desc())
        )).scalars().all()
        sessions = [
            {
                "id": r.id,
                "machine_id": r.machine_id,
                "guest_id": r.guest_id,
                "started_at": r.started_at.isoformat() if r.started_at else None,
            }
            for r in active_rows
        ]
        zf.writestr("active_sessions.json", json.dumps(sessions, indent=2, default=str))

        # Aktivitätslog (letzte 200)
        log_rows = (await db.execute(
            select(ActivityLog)
            .order_by(ActivityLog.created_at.desc())
            .limit(200)
        )).scalars().all()
        log_entries = [
            {
                "id": r.id,
                "type": r.type.value if hasattr(r.type, "value") else str(r.type),
                "message": r.message,
                "guest_id": r.guest_id,
                "machine_id": r.machine_id,
                "user_id": r.user_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in log_rows
        ]
        zf.writestr("activity_log.json", json.dumps(log_entries, indent=2, default=str))

        # Update-Watcher-Log
        if LOG_FILE.exists():
            zf.write(LOG_FILE, "update.log")

    buf.seek(0)
    filename = f"spacecaptain-bundle-{now.strftime('%Y%m%d-%H%M%S')}.zip"
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
