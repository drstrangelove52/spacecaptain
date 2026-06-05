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
- `DELETE()` unterstützt optionalen Body: `DELETE(path, body)`
- `downloadBackupFile()` nutzt eigenen `fetch`-Aufruf (braucht Blob-Handling, nicht JSON)

## Wichtige Dateien

```
backend/app/
  models.py                  — ORM: alle Tabellen
  services/migrate.py        — Migrationen (idempotent, laufen bei jedem Start)
  services/rule_watcher.py   — Kombinierter Automations-Watcher (10s Intervall)
  services/room.py           — open_room() / close_room() mit force_off-Logik
  services/session.py        — Idle-Watcher, Plug-Watcher
  services/backup_service.py — Backup-Logik, BACKUP_DIR, backup_watcher()
  routers/automations.py     — Regelwerk CRUD (action_type: machine|room_open|room_close|notify)
  routers/categories.py      — Maschinenkategorien CRUD
  routers/locations.py       — Maschinenstandorte CRUD
  routers/guest_auth.py      — Gast-Zugang inkl. Raum-Sperre
  routers/backup.py          — Backup REST-Endpoints

frontend/
  labmanager.html            — Komplette Admin-UI (single file, kein Framework)
  index.html                 — Gäste-App
  display.html               — Kiosk/Display-Seite
```

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

**Was ist im Backup enthalten:** Einstellungen, Benutzer, Gäste, Maschinen, Plug-Pool, Berechtigungen, Sessions, Aktivitätslog, Wartungsintervalle, Wartungshistorie, Aushänge, ntfy-Topics, Automationsregeln, Standorte.

## Hintergrund-Tasks

In `backend/app/main.py` werden 5 Tasks im FastAPI-Lifespan gestartet:

| Task | Datei | Funktion |
|---|---|---|
| Idle-Watcher | `services/session.py` | Beendet Sessions bei Leerlauf |
| Plug-Watcher | `services/session.py` | Pollt Smart-Plug-Status |
| Queue-Watcher | `services/queue_service.py` | Verarbeitet Warteliste |
| Backup-Watcher | `services/backup_service.py` | Tägliches Auto-Backup |
| Rule-Watcher | `services/rule_watcher.py` | Automationsregeln (10s Intervall) |

Alle Tasks werden beim Shutdown mit `.cancel()` beendet.

## Automations-Regelwerk

Jede Regel hat einen `action_type` (`machine` / `room_open` / `room_close` / `notify`) und beliebig viele AND-verknüpfte Bedingungen (`power`, `schedule`, `room_open`, `session_active`).

**Zustandsautomat pro Regel:** `idle` → `on` → `countdown` → `idle`

**Aktionstypen:**
- `machine`: schaltet Ziel-Maschine (mit Plug) ein/aus, Nachlaufzeit möglich
- `room_open` / `room_close`: feuert einmalig (idle → on), kein target_machine_id nötig
- `notify`: sendet ntfy-Push an `notify_topic_id` mit `notify_message`, feuert einmalig

**Wichtiges Verhalten bei Raum- und Notify-Aktionen:**
- Die Aktion feuert **einmalig** wenn alle Bedingungen wahr werden (idle → on)
- Wenn Bedingungen wieder falsch werden, wird nur der Rule-State auf `idle` zurückgesetzt
- Das Zeitplan-Ende (`time_off`) schiesst den Raum/Notify **nicht** automatisch — setzt nur State zurück
- Für zeitgesteuertes Öffnen **und** Schliessen braucht es zwei separate Regeln

**Raum-Bedingung (`room_open`) ist bei Raum-Aktionen nicht sinnvoll** und im UI ausgefiltert.

OR-Verknüpfung in Bedingungen ist bewusst nicht implementiert — zwei separate Regeln ersetzen das ohne UX-Komplexität.

## Raum-Logik

- `force_off_on_close` Flag pro Maschine: beim Raumschluss werden nur Maschinen mit diesem Flag ausgeschaltet (z.B. Kaffeemaschine, Lötstation). 3D-Drucker laufen über Nacht weiter.
- Laufende Maschinen-Sessions werden beim Raumschluss **nicht** unterbrochen (by design). Der Gast kann die Maschine noch ausschalten, neue Sessions sind aber gesperrt.
- Gast-App: HTTP 403 vom Backend enthält `detail: "Raum ist geschlossen"` und wird im UI als eigenes Panel angezeigt (kein stiller Logout).

## Maschinenkategorien und Standorte

- Kategorien (`machine_categories`) und Standorte (`machine_locations`) sind vordefinierte Listen, die in den Maschinen-Formularen als `<select>` erscheinen.
- Verwaltung via Topbar-Buttons «⚙ Kategorien» und «⚙ Standorte» auf der Maschinen-Seite.
- **CSV-Import** legt fehlende Kategorien und Standorte automatisch an (`import/confirm`-Endpoint in `routers/machines.py`).
- Beide Tabellen sind vollständig im Backup enthalten.
- Frontend: `cache.categories` / `cache.locations`, `_catOptions()` / `_locOptions()`, `_refreshCatFilter()` / `_refreshLocFilter()`.

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

Die Einstellungs-Seite im Frontend ist als Hilfe-Layout organisiert (7 Kategorien: System, Display, Aushänge, AGB, Push-Nachrichten, Notfall-Alarm, Auto-Backup). Neue Felder in der passenden Kategorie ergänzen.

## Notfall-Alarm

- Sirene und Blinklicht werden über den **Plug-Pool** konfiguriert: `emergency_plug_id` und `emergency_plug2_id` in `SystemSettings` (FK auf `plugs.id`)
- `_switch_emergency_plugs(plug1_id, plug2_id, action, db)` in `routers/emergency.py` lädt den Plug per ID aus der DB
- `_auto_stop_plugs(plug1_id, plug2_id, duration_sec)` läuft als asyncio-Task und öffnet nach dem Sleep eine eigene DB-Session (`AsyncSessionLocal`) — die Request-Session ist zu diesem Zeitpunkt längst geschlossen

**Backup-Besonderheit:** `emergency_plug_id`/`emergency_plug2_id` sind DB-interne IDs. Im Backup werden sie als `emergency_plug_ip_ref`/`emergency_plug2_ip_ref` (Plug-IP-Adresse) exportiert und beim Import nach Plug-Import wieder zu IDs aufgelöst. So bleibt ein Restore auf einer anderen Instanz korrekt.

## Rollen

- **Admin**: voller Zugriff, darf Gäste/Maschinen löschen
- **Lab Manager**: darf deaktivieren, aber nicht löschen — verhindert versehentlichen Datenverlust, Gast-History bleibt erhalten

## Berechtigungshistorie (UI)

`GET /permissions/history?guest_id=X` gibt den neuesten `ActivityLog`-Eintrag pro Maschine zurück (Typ `permission_granted` / `permission_revoked`). Der `comment` kommt aus `entry.meta["comment"]`. Das UI zeigt diesen Kommentar in der Berechtigungsmatrix.

Beim Overwrite-Restore: falls `is_blocked` sich ändert, wird ein neuer `ActivityLog`-Eintrag geschrieben, damit die Historie den wiederhergestellten Zustand zeigt.

## Terminologie

- **Aushänge** (nicht "Mitteilungen"): zeitgesteuerte Ankündigungen für Gäste (`announcements`)
- **Push-Nachrichten** (nicht "Benachrichtigungen"): ntfy-basierte Push-Nachrichten

## Bekannte Einschränkungen / Offene Punkte

| Thema | Beschreibung |
|---|---|
| Raum-Session-Hinweis | Wenn Raum bei laufender Session geschlossen wird, läuft Session weiter (by design) — kein UI-Hinweis vorhanden |
| Doppelter Log-Eintrag | `room_close`-Regel mit Zeitplan triggert täglich neu → kosmetisch doppelter Log |
| API Raum-Steuerung | `open_room()` / `close_room()` in `services/room.py` bereit, kein öffentlicher API-Endpoint (z.B. für Home Assistant / Türöffner) |

## Häufige Befehle

```bash
# Starten (mit Build-Nummer im Sidebar-Footer)
BUILD_NR=$(git rev-list --count HEAD) docker compose up -d

# Backend-Logs beobachten
docker compose logs -f backend

# Neu bauen (nach Dependency-Änderungen)
BUILD_NR=$(git rev-list --count HEAD) docker compose up -d --build backend

# DB-Shell
docker compose exec db mariadb -u spacecaptain -p spacecaptain
```

## Was vermeiden

- `--reload` ohne `--reload-dir /app/app` — WatchFiles überwacht sonst `/app/backups` und löst bei jedem neuen Backup-File einen Reload aus
- Imports aus `backup.py` auf Modulebene in `backup_service.py` — zirkulärer Import
- Neue Settings-Felder nur in `models.py` eintragen — `SettingsOut`/`SettingsUpdate` in `settings.py` und Migration vergessen
- Bei `automations.py` Log-Nachrichten `tm.name` verwenden ohne zu prüfen ob `tm` None ist — bei `room_open`/`room_close`/`notify`-Aktionen gibt es keine Ziel-Maschine
- Neue Backup-Sektionen ohne `payload.get("sektion", [])` lesen — bricht ältere Backups
- `emergency_plug_id`/`emergency_plug2_id` direkt in den Settings exportieren — sind DB-interne IDs, müssen als IP-Referenz exportiert und beim Import aufgelöst werden (siehe Notfall-Alarm-Sektion)
