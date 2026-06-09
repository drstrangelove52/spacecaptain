"""
Tailscale-Fernzugriff
=====================
Schreibt Aktions-Trigger für den Host-Updater (spacecaptain-updater.sh).
Der Updater startet oder stoppt den tailscale-Container und schreibt
anschliessend den Status in update_trigger/tailscale_status.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services.auth import require_admin
from app.services.system_settings import get_system_settings

router = APIRouter(prefix="/tailscale", tags=["tailscale"])

_TRIGGER_DIR = Path("/app/update_trigger")
_ACTION_FILE  = _TRIGGER_DIR / "tailscale_action"
_STATUS_FILE  = _TRIGGER_DIR / "tailscale_status"
_STATE_FILE   = Path("/app/tailscale-state/tailscaled.state")


@router.post("/apply")
async def tailscale_apply(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Löst Tailscale-Aktion aus (enable/disable) basierend auf aktuellen Settings."""
    if not _TRIGGER_DIR.exists():
        raise HTTPException(
            503,
            "Trigger-Verzeichnis nicht erreichbar — Update-Watcher muss eingerichtet sein",
        )
    s = await get_system_settings(db)
    if s.ts_enabled:
        authkey  = (s.ts_authkey or "").strip()
        hostname = (s.ts_hostname or "spacecaptain").strip() or "spacecaptain"
        _ACTION_FILE.write_text(f"enable\n{authkey}\n{hostname}")
        # Auth-Key nach Trigger löschen — wird nicht mehr benötigt
        s.ts_authkey = None
        await db.commit()
    else:
        _ACTION_FILE.write_text("disable")
    return {"triggered": True, "action": "enable" if s.ts_enabled else "disable"}


@router.get("/status")
async def tailscale_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Ermittelt Tailscale-Status aus drei Quellen:
    1. tailscale_status-Datei (vom Updater nach Trigger geschrieben)
    2. tailscaled.state-Datei (beweist erfolgreiche Verbindung in der Vergangenheit)
    3. ts_enabled in Settings (konfigurierter Sollzustand)
    """
    s = await get_system_settings(db)
    file_status = _STATUS_FILE.read_text().strip() if _STATUS_FILE.exists() else None
    ever_connected = _STATE_FILE.exists()

    if not s.ts_enabled:
        status = "stopped" if file_status in ("stopped", "running") else "disabled"
    elif file_status in ("running", "starting", "error", "stopped"):
        status = file_status
    elif ever_connected:
        # State-Datei vorhanden → Container läuft wahrscheinlich (nach Neustart reconnected)
        status = "running"
    else:
        # Aktiviert, aber noch nie verbunden
        status = "pending"

    return {
        "status": status,
        "watcher_ready": _TRIGGER_DIR.exists(),
        "ever_connected": ever_connected,
    }
