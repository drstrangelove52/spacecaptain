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
_ACTION_FILE = _TRIGGER_DIR / "tailscale_action"
_STATUS_FILE = _TRIGGER_DIR / "tailscale_status"


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
async def tailscale_status(_: User = Depends(require_admin)):
    """Gibt den letzten bekannten Tailscale-Status zurück."""
    status = "unknown"
    if _STATUS_FILE.exists():
        status = _STATUS_FILE.read_text().strip()
    return {"status": status, "watcher_ready": _TRIGGER_DIR.exists()}
