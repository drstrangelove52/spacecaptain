from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException

from app.services.auth import require_admin
from app.models import User
from app.config import APP_VERSION, BUILD_NR

router = APIRouter(prefix="/update", tags=["update"])

TRIGGER_DIR = Path("/app/update_trigger")
TRIGGER_FILE = TRIGGER_DIR / "trigger"
LOG_FILE = TRIGGER_DIR / "update.log"
STATUS_FILE = TRIGGER_DIR / "update.status"


@router.get("/status")
async def get_update_status(_: User = Depends(require_admin)):
    watcher_ready = TRIGGER_DIR.exists()
    last_triggered = None
    if LOG_FILE.exists():
        last_triggered = datetime.fromtimestamp(LOG_FILE.stat().st_mtime).isoformat()
    last_result = STATUS_FILE.read_text().strip() if STATUS_FILE.exists() else None
    return {
        "version": APP_VERSION,
        "build": BUILD_NR,
        "pending": TRIGGER_FILE.exists(),
        "watcher_ready": watcher_ready,
        "last_triggered": last_triggered,
        "last_result": last_result,
    }


@router.post("/trigger")
async def trigger_update(_: User = Depends(require_admin)):
    if not TRIGGER_DIR.exists():
        raise HTTPException(
            status_code=503,
            detail="Update-Verzeichnis nicht gemountet — Update-Watcher nicht eingerichtet"
        )
    if TRIGGER_FILE.exists():
        raise HTTPException(status_code=409, detail="Update läuft bereits")
    TRIGGER_FILE.write_text(datetime.now().isoformat())
    return {"status": "triggered"}
