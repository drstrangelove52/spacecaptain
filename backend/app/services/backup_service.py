"""
Automatisches Backup — Hintergrund-Watcher.
Erstellt täglich zur konfigurierten Stunde ein JSON-Backup unter /app/backups/.
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from app.database import AsyncSessionLocal
from app.services.system_settings import get_system_settings

log = logging.getLogger(__name__)

BACKUP_DIR = Path("/app/backups")


def _list_backup_files() -> list[Path]:
    """Gibt alle Backup-Dateien sortiert nach Änderungszeit zurück (älteste zuerst)."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(
        [f for f in BACKUP_DIR.iterdir() if f.suffix == ".json" and f.name.startswith("spacecaptain_backup_")],
        key=lambda f: f.stat().st_mtime,
    )


async def backup_watcher(app) -> None:
    """Prüft alle 30 Sekunden ob ein tägliches Backup fällig ist."""
    last_backup_date: str | None = None

    while True:
        try:
            await asyncio.sleep(30)
            async with AsyncSessionLocal() as db:
                cfg = await get_system_settings(db)
                if not cfg.auto_backup_enabled:
                    continue

                now = datetime.now()  # lokale Serverzeit (TZ aus Umgebungsvariable)
                today = now.strftime("%Y-%m-%d")

                if last_backup_date == today:
                    continue

                scheduled = now.replace(
                    hour=cfg.auto_backup_hour,
                    minute=cfg.auto_backup_minute,
                    second=0, microsecond=0,
                )
                if now < scheduled:
                    continue

                try:
                    path = await _create_backup(db)
                    last_backup_date = today
                    log.info(f"Auto-Backup erstellt für {today} (konfiguriert: {cfg.auto_backup_hour:02d}:{cfg.auto_backup_minute:02d} Lokalzeit)")
                    _cleanup_old_backups(cfg.auto_backup_keep)
                    await _upload_remote(db, path)
                except Exception as e:
                    log.error(f"Auto-Backup fehlgeschlagen: {e}", exc_info=True)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"backup_watcher Fehler: {e}", exc_info=True)
            await asyncio.sleep(30)


async def _create_backup(db) -> Path:
    """Erstellt ein Backup und schreibt es ins Backup-Verzeichnis. Gibt den Dateipfad zurück."""
    from app.routers.backup import _build_export_data
    data = await _build_export_data(db)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"spacecaptain_backup_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    path = BACKUP_DIR / filename
    path.write_text(json.dumps(data, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _cleanup_old_backups(keep: int) -> None:
    """Löscht älteste Backup-Dateien, bis nur noch `keep` Stück übrig bleiben."""
    files = _list_backup_files()
    for f in files[:-keep] if len(files) > keep else []:
        try:
            f.unlink()
            log.info(f"Altes Backup gelöscht: {f.name}")
        except Exception as e:
            log.warning(f"Backup löschen fehlgeschlagen ({f.name}): {e}")


async def _upload_remote(db, path: Path) -> None:
    """Lädt ein Backup per SFTP aufs konfigurierte NAS hoch, falls aktiviert.
    Rein additiv zur lokalen Aufbewahrung — lokale Backups werden dadurch nicht angetastet.
    Schreibt Ergebnis/Fehler in system_settings, damit der Status ohne Server-Logs im UI sichtbar ist."""
    cfg = await get_system_settings(db)
    if not cfg.backup_remote_enabled:
        return
    from app.services import remote_backup
    try:
        await asyncio.to_thread(remote_backup.upload_file_sync, cfg, path)
        cfg.backup_remote_last_status = "ok"
        cfg.backup_remote_last_message = f"{path.name} erfolgreich hochgeladen"
        log.info(f"SFTP-Upload erfolgreich: {path.name} → {cfg.backup_remote_host}")
    except Exception as e:
        cfg.backup_remote_last_status = "error"
        cfg.backup_remote_last_message = str(e)[:1000]
        log.error(f"SFTP-Upload fehlgeschlagen für {path.name}: {e}", exc_info=True)
    cfg.backup_remote_last_at = datetime.utcnow()
    await db.commit()
