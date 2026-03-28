# SpaceCaptain — Projekt-Kontext für Claude Code

## Was ist SpaceCaptain?

Maschinen-Zugangsmanagement für Maker-/FabLabs. Gäste scannen QR-Codes an Maschinen, der Server prüft ihre Berechtigung und schaltet optional einen Smart Plug (myStrom / Shelly) ein. Lab-Manager verwalten Gäste, Berechtigungen, Wartungsintervalle und Benachrichtigungen über ein Web-UI.

## Architektur

```
nginx (Reverse Proxy, HTTPS)
├── frontend/   — Statisches HTML/JS (Single-Page, kein Framework)
├── backend/    — FastAPI + SQLAlchemy async + MariaDB
└── db/         — MariaDB 11
```

Alle Services laufen in Docker Compose. Die Konfiguration erfolgt via `.env`.

**Backend-Stack:**
- FastAPI, Uvicorn (mit `--reload-dir /app/app` — nur Python-Verzeichnis, nicht `/app/backups`)
- SQLAlchemy async ORM mit `aiomysql`
- Pydantic v2 für Settings (`pydantic-settings`)
- JWT-Auth für Manager/Admins, eigenes Token-System für Gäste

**Frontend:**
- Eine einzige `labmanager.html` — kein Build-Schritt, kein Framework
- `GET/POST/PATCH/DELETE`-Wrapper: `api()`, `GET()`, `POST()`, `PATCH()`, `DELETE()` in der HTML-Datei
- `downloadBackupFile()` nutzt eigenen `fetch`-Aufruf (braucht Blob-Handling, nicht JSON)

## Datenbankschema-Migrationen

Migrationen laufen **bei jedem Backend-Start** in `backend/app/services/migrate.py`.

**Regeln:**
- Nur `ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` — nie destruktiv
- Neue Spalten mit `_add_column_if_missing(conn, tabelle, spalte, "TYP DEFAULT x")`
- Neue Spalten gleichzeitig in `backend/app/models.py` (SQLAlchemy ORM) und `db/init.sql` (für Neuinstallationen) eintragen

## Backup-System

- **`backend/app/services/backup_service.py`**: `BACKUP_DIR`, `_list_backup_files()`, `backup_watcher()` (Hintergrund-Task), `_create_backup()`, `_cleanup_old_backups()`
- **`backend/app/routers/backup.py`**: REST-Endpoints, importiert `BACKUP_DIR` und `_list_backup_files` aus `backup_service`
- Zirkulärer Import: `backup_service` importiert `_build_export_data` aus `backup.py` — deshalb **innerhalb** von `_create_backup()`, nicht auf Modulebene

**Backup-Kompatibilitätsregeln** (in `_do_import` dokumentiert):
- Neue Felder in Datensätzen immer mit `.get("feld", default)` lesen
- Neue Top-Level-Sektionen mit `payload.get("sektion", [])` lesen
- Nie `payload["key"]` ohne Existenzprüfung

## Hintergrund-Tasks

In `backend/app/main.py` werden 4 Tasks im FastAPI-Lifespan gestartet:

| Task | Datei | Funktion |
|---|---|---|
| Idle-Watcher | `services/session.py` | Beendet Sessions bei Leerlauf |
| Plug-Watcher | `services/session.py` | Pollt Smart-Plug-Status |
| Queue-Watcher | `services/queue_service.py` | Verarbeitet Warteliste |
| Backup-Watcher | `services/backup_service.py` | Tägliches Auto-Backup |

Alle Tasks werden beim Shutdown mit `.cancel()` beendet.

## Zeitzone

- `TZ`-Umgebungsvariable im Container steuert die lokale Zeit
- `datetime.now()` liefert Lokalzeit — für Backupnamen, Scheduler etc.
- `datetime.utcnow()` nur für DB-Timestamps (historische Konsistenz)
- **Nicht** `datetime.now(timezone.utc)` mischen

## Settings

Systemweite Einstellungen leben in `system_settings` (DB-Tabelle, immer genau eine Zeile).

Bei neuen Einstellungsfeldern müssen **drei Stellen** aktualisiert werden:
1. `backend/app/models.py` — `SystemSettings`-Klasse
2. `backend/app/routers/settings.py` — `SettingsOut`, `SettingsUpdate`, PATCH-Handler
3. `backend/app/services/migrate.py` — Migration + `db/init.sql`

## Berechtigungshistorie (UI)

`GET /permissions/history?guest_id=X` gibt den neuesten `ActivityLog`-Eintrag pro Maschine zurück (Typ `permission_granted` / `permission_revoked`). Der `comment` kommt aus `entry.meta["comment"]`. Das UI zeigt diesen Kommentar in der Berechtigungsmatrix.

Beim Overwrite-Restore: falls `is_blocked` sich ändert, wird ein neuer `ActivityLog`-Eintrag geschrieben, damit die Historie den wiederhergestellten Zustand zeigt.

## Häufige Befehle

```bash
# Starten
docker compose up -d

# Backend-Logs beobachten
docker compose logs -f backend

# Neu bauen (nach Dependency-Änderungen)
docker compose up -d --build backend

# DB-Shell
docker compose exec db mariadb -u spacecaptain -p spacecaptain
```

## Was vermeiden

- `--reload` ohne `--reload-dir /app/app` — WatchFiles überwacht sonst `/app/backups` und löst bei jedem neuen Backup-File einen Reload aus
- Imports aus `backup.py` auf Modulebene in `backup_service.py` — zirkulärer Import
- Neue Settings-Felder nur in `models.py` eintragen und vergessen → `SettingsOut`/`SettingsUpdate` in `settings.py` ebenfalls anpassen
