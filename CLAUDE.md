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
  services/remote_backup.py  — SFTP-Upload aufs externe NAS (Passwort/Key-Auth, paramiko)
  routers/automations.py     — Regelwerk CRUD (action_type: machine|room_open|room_close|notify)
  routers/categories.py      — Maschinenkategorien CRUD
  routers/locations.py       — Maschinenstandorte CRUD
  routers/owners.py          — Maschinen-Eigentümer CRUD (Lookup-Tabelle wie locations.py)
  routers/batteries.py       — Akku-Verwaltung CRUD (eigene Seite im Frontend, kein Machine-Bezug)
  routers/guest_auth.py      — Gast-Zugang inkl. Raum-Sperre
  routers/backup.py          — Backup REST-Endpoints
  routers/update.py          — In-App Update: GET /status + POST /trigger (schreibt update_trigger/trigger)

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
- Spalte umbenennen mit `_rename_column_if_needed(conn, tabelle, alt, neu, "TYP DEFAULT x")` (idempotent: nur wenn alt existiert und neu noch nicht) — **zusätzlich** den Backup-Restore mit Fallback auf den alten Schlüssel versehen (`payload.get("neu", payload.get("alt"))`), sonst verlieren ältere Backups den Wert (Beispiel: `batteries.price_new` → `value_new`, Migration v1.41, `routers/backup.py`)
- Neue Spalten in `backend/app/models.py` (SQLAlchemy ORM) eintragen. `db/init.sql` **nicht** zwingend nachziehen — es ist in der Praxis schon länger nicht mehr aktuell (z.B. fehlt dort die `power_manager`-Rolle im `users.role`-ENUM) und trotzdem unkritisch: `migrate.py` läuft bei **jedem** Start und zieht fehlende Spalten/ENUM-Werte automatisch nach, auch direkt nach einer frischen `init.sql`-Installation. `init.sql` ist nur die MariaDB-`docker-entrypoint-initdb.d`-Basis für ein leeres Datenvolume, nicht die Quelle der Wahrheit fürs Schema. Neue **Tabellen** (z.B. `machine_owners`, `batteries`) brauchen dort ohnehin nichts, die entstehen automatisch über `Base.metadata.create_all()` beim Start.

## Backup-System

- **`backend/app/services/backup_service.py`**: `BACKUP_DIR`, `_list_backup_files()`, `backup_watcher()` (Hintergrund-Task), `_create_backup()`, `_cleanup_old_backups()`
- **`backend/app/routers/backup.py`**: REST-Endpoints, importiert `BACKUP_DIR` und `_list_backup_files` aus `backup_service`
- Zirkulärer Import: `backup_service` importiert `_build_export_data` aus `backup.py` — deshalb **innerhalb** von `_create_backup()`, nicht auf Modulebene

**Backup-Kompatibilitätsregeln** (in `_do_import` dokumentiert):
- Neue Felder in Datensätzen immer mit `.get("feld", default)` lesen
- Neue Top-Level-Sektionen mit `payload.get("sektion", [])` lesen
- Nie `payload["key"]` ohne Existenzprüfung

**Was ist im Backup enthalten:** Einstellungen (inkl. Währung), Benutzer (inkl. `login_token`), Gäste (inkl. `login_token`/`pending_approval`), Maschinen (inkl. Kaufdatum/Neuwert/Eigentümer/`total_hours`), Plug-Pool, Berechtigungen, Sessions, Aktivitätslog, Wartungsintervalle, Wartungshistorie, Aushänge, ntfy-Topics, Automationsregeln, Kategorien, Standorte, Eigentümer, Akkus.

**`total_hours`-Falle (behoben):** War zwar im Export enthalten, wurde beim Restore aber nie direkt zurückgeschrieben — nur indirekt aus `sessions` rekonstruiert (`hours_accumulator`, greift nur wenn `total_hours == 0.0`). Bei Overwrite auf eine bestehende Maschine blieb der alte Wert also stehen. Jetzt in beiden Machine-Restore-Zweigen direkt gesetzt (`m.get("total_hours", ...)`); die Session-Rekonstruktion bleibt als Fallback nur noch für sehr alte Backups (vor Einführung von `total_hours` im Export) relevant.

**`login_token`-Restore-Verhalten:** Bei Overwrite auf einen bestehenden User/Gast wird `login_token` wie `password_hash` behandelt — `u.get("login_token", row.login_token)` statt direktem Zuweisen. Fehlt das Feld im Backup (ältere Backups vor diesem Fix), bleibt der aktuell aktive Token unangetastet statt auf `None` zurückgesetzt zu werden — sonst würde ein Restore mit altem Backup-Format ein aktives Token-Login (Magic-Link ohne Passwort) stillschweigend invalidieren.

**Nicht im Backup (bewusst, transienter Laufzeitzustand statt Konfiguration):** `emergency_state` (aktueller Alarm-Status), `machine_queue` (aktuelle Warteliste). Legacy-Tabellen `device_schedules` und `machine_automations` sind seit der Migration auf `automation_rules`/`rule_conditions` inaktiv (kein Router mehr registriert) und daher ebenfalls nicht enthalten. Ebenfalls ausgeschlossen: `backup_remote_password`/`-private_key`/`-key_passphrase` sowie `backup_remote_last_status`/`-message`/`-at` (siehe unten) — erste Gruppe sind Secrets, deren Export ein zusätzliches Leak-Risiko wäre (Zugangsdaten zum eigenen Backup-Ziel), zweite Gruppe ist reiner Laufzeitstatus.

### Externes SFTP-Backup (`services/remote_backup.py`, Migration v1.42)

Optionaler, additiver Upload jedes lokal erstellten Backups auf ein externes NAS. Komplett UI-konfigurierbar (Einstellungen → Externes Backup) — löst den früher offenen Architektur-Konflikt "NFS-Host-Mount vs. UI-Config" zugunsten von App-Level-SFTP: keine `.env`/Host-Berührung nötig, Zugangsdaten leben wie `ts_authkey`/`ntfy_token` in `system_settings`.

- **`services/remote_backup.py`**: `_connect()` (Passwort oder Key-Auth per `paramiko`), `upload_file_sync()`, `test_connection_sync()` — alles synchron/blockierend, aus async Code immer per `asyncio.to_thread()` aufrufen
- Key-Auth schreibt den PEM-Key temporär in eine Datei (`tempfile.mkstemp`, `chmod 600`, danach `os.unlink()` im `finally`) — `paramiko` erkennt den Schlüsseltyp (RSA/Ed25519/ECDSA/DSS) nur über `key_filename`, nicht aus einem In-Memory-String
- Host-Key-Policy ist `AutoAddPolicy` (TOFU, kein Pinning) — bewusste Vereinfachung, kein `known_hosts`-Speicher im Container vorgesehen
- **Rein additiv**: verändert die bestehende lokale Aufbewahrung (`auto_backup_keep`) nicht. Läuft nach `_create_backup()` in `backup_watcher()` (Auto-Backup) und in `POST /backup/files/create` (manuell), nicht beim Restore
- Ergebnis (Erfolg/Fehler) wird in `backup_remote_last_status`/`-last_message`/`-last_at` geschrieben und im Settings-Panel angezeigt — ohne das würde ein kaputtes NAS-Ziel nur in den Docker-Logs auffallen
- `POST /backup/remote-test` prüft Verbindung + Schreibrechte separat (Schreibtest mit `.spacecaptain_test`-Datei, wird sofort wieder gelöscht), ohne ein echtes Backup zu erzeugen
- Frontend-Pattern für Passwort/Key: identisch zu `ts_authkey` — nach jedem Laden werden die Secret-Felder geleert (`loadSettings()`), leer lassen beim Speichern heisst "unverändert" (PATCH-Handler: `if payload.x is not None: row.x = payload.x or None` — explizites `null` im JSON ist nach Pydantic-Parsing nicht von "Feld weggelassen" unterscheidbar, siehe `ts_authkey`-Vorbild)

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

## Maschinenkategorien, Standorte und Eigentümer

- Kategorien (`machine_categories`), Standorte (`machine_locations`) und Eigentümer (`machine_owners`) sind vordefinierte Listen, die in den Maschinen-Formularen als `<select>` erscheinen. Alle drei sind schlanke Lookup-Tabellen (`id`/`name`/`sort_order`, Kategorien zusätzlich `icon`) ohne Auth/Rechte-Bezug.
- Verwaltung via Topbar-Buttons «⚙ Kategorien», «⚙ Standorte» und «⚙ Eigentümer» auf der Maschinen-Seite.
- **CSV-Import** legt fehlende Kategorien, Standorte und Eigentümer automatisch an (`import/confirm`-Endpoint in `routers/machines.py`).
- **CSV-Import kann bestehende Maschinen aktualisieren**: Export enthält eine `ID`-Spalte, beim Re-Import wird darüber gematcht (`existing_by_id`-Lookup in `_parse_csv_row`). Zeilen mit passender ID werden als Action `"update"` markiert, aber nur angewendet wenn der Import mit der Checkbox "Bestehende aktualisieren" (`update_existing: bool` im `/import/confirm`-Payload) bestätigt wird — sonst wie bisher übersprungen. Leere Zellen leeren dabei das jeweilige Feld (CSV gilt als vollständiger Datensatz), nur die ID selbst dient rein dem Matching und wird nie geschrieben.
- Alle drei Tabellen sind vollständig im Backup enthalten.
- Frontend: `cache.categories` / `cache.locations` / `cache.owners`, `_catOptions()` / `_locOptions()` / `_ownerOptions()`, `_refreshCatFilter()` / `_refreshLocFilter()`.

## Inventar (Kaufdatum, Neuwert, Eigentümer) und Akku-Verwaltung

- `Machine` hat drei nullable Buchhaltungs-/Versicherungsfelder: `purchase_date`, `value_new`, `owner_id` (FK → `machine_owners`). Unüberwachte Maschinen (kein Plug) sind einfach `Machine`-Einträge ohne Plug-Zuordnung — bewusst kein separates "Inventory Item"-Modell.
- **Akkus** (`batteries`, `routers/batteries.py`) sind ein eigenständiger Verbrauchsmaterial-Pool ohne Machine-Bezug: Hersteller, Modell, Kaufdatum, Neuwert (`value_new`, bis Migration v1.41 `price_new` — auf `Machine.value_new` vereinheitlicht, siehe Kompatibilitätshinweis unten), Status (`aktiv`/`defekt`/`ausgemustert`). Eigene Seite unter AUSSTATTUNG im Frontend (nicht in der Maschinen-Sektion), bedienungsmässig identisch zum Plug-Pool (sortierbare Tabelle, Suche/Status-Filter, Modal für Anlegen/Bearbeiten).
- **Inventarliste für Buchhaltung**: Button «📋 Inventarliste» auf der Maschinen-Seite exportiert nur die buchhaltungsrelevanten Felder (Name, Kategorie, Hersteller, Modell, Seriennummer, Standort, Kaufdatum, Neuwert, Eigentümer + Summenzeile) als CSV oder Druckansicht (PDF via Browser-Druckdialog, kein PDF-Backend nötig) — bewusst getrennt von der operativen CSV (`exportMachinesCsv()`), die zusätzlich Status/Schulung/Smart-Plug/Kommentar enthält.
- Migration v1.39.

## Display/Dashboard-Sichtbarkeit

Seit die Maschinenliste auch reine Inventar-Einträge ohne Plug abdeckt (Buchhaltung/Versicherung), filtern die operativen Ansichten konsistent:

- **Display/Kiosk** (`display.html`) und **Gast-App** (`index.html`, nutzen beide `GET /guest/dashboard`): Backend filtert serverseitig auf `Machine.plug_id.is_not(None)` (`routers/guest_auth.py`) — reine Inventar-Einträge ohne Plug tauchen dort nie auf. Zusätzlich filtert `display.html` clientseitig `status !== 'offline'` weg (kombiniert: kein Plug ODER gesperrt → unsichtbar).
- **Dashboard** (`labmanager.html`, `renderDashboard()`): eigene Teilmengen, da die Stat-Kachel "Maschinen online" gesperrte Maschinen im Nenner braucht (sonst ergibt "X von Y" keinen Sinn), das Maschinen-Grid darunter aber 1:1 wie das Display gefiltert sein soll:
  - `monitorable` = `plug_id != null` — Basis für die Stat-Kachel (Zähler + "von X gesamt")
  - `displayLike` = `monitorable` zusätzlich ohne `status === 'offline'` — für das Maschinen-Grid, spiegelt exakt die Display-Logik
  - "Aktive Sessions"/"Aktive Maschinen"-Tabelle bleibt bewusst auf Basis **aller** Maschinen (eine laufende Session ist immer real und soll sichtbar bleiben, unabhängig vom Plug-Status)
- **Adapter-Offline** (Plug konfiguriert, aber gerade nicht erreichbar — `plug_supported && plug_error === 'unreachable'`, siehe `services/plug.py` `get_plug_status()`) ist ein eigenes Konzept, getrennt vom `status`-Feld. Wird identisch in `display.html` ("ADAPTER OFFLINE"), der Maschinen-Tabelle ("⚠ n. erreichbar") und dem Dashboard-Grid ("⚠ ADAPTER OFFLINE") angezeigt — wenn hier eine neue Ansicht für Maschinen entsteht, diese Unterscheidung mitziehen, sonst sieht ein Plug mit falscher/toter IP identisch aus wie "kein Plug" oder "normal online".
- Dashboard-Grid zeigt "In Wartung" (`status === 'maintenance'`) zusätzlich als Text-Tag, nicht nur über die Punktfarbe — 1:1 wie Display, das den Status immer ausschreibt statt nur farblich zu codieren.

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

**Beispiel `currency`** (Migration v1.40, Default `"CHF"`): zeigt alle nötigen Stellen für ein einfaches Textfeld.
- `models.py` / `settings.py` (Out+Update+PATCH-Handler) / `migrate.py` wie oben beschrieben
- Zusätzlich in `routers/settings.py` → `read_settings_public()` aufgenommen, weil das Feld auch für nicht-admin Rollen sichtbar sein muss (Maschinen-/Akku-Formulare, Inventarliste — alle nutzen `/settings/public`, nicht das admin-only `/settings`)
- Frontend: globale Variable `_currency` (gesetzt aus dem `/api/settings/public`-Fetch beim Seitenaufruf und erneut in `loadSettings()`), Helper `_applyCurrencyLabels()` aktualisiert statische Modal-Labels (z.B. Akku-Formular) zur Laufzeit — dynamisch generierte Formulare (Maschine hinzufügen/bearbeiten) interpolieren `${_currency}` direkt beim Rendern
- **Falle:** Pydantic-Schema (`SettingsOut`/`SettingsUpdate`) allein reicht nicht — der PATCH-Handler in `update_settings()` setzt jedes Feld einzeln (`if payload.x is not None: row.x = ...`), das leicht vergessen wird

## Notfall-Alarm

- Sirene und Blinklicht werden über den **Plug-Pool** konfiguriert: `emergency_plug_id` und `emergency_plug2_id` in `SystemSettings` (FK auf `plugs.id`)
- `_switch_emergency_plugs(plug1_id, plug2_id, action, db)` in `routers/emergency.py` lädt den Plug per ID aus der DB
- `_auto_stop_plugs(plug1_id, plug2_id, duration_sec)` läuft als asyncio-Task und öffnet nach dem Sleep eine eigene DB-Session (`AsyncSessionLocal`) — die Request-Session ist zu diesem Zeitpunkt längst geschlossen

**Backup-Besonderheit:** `emergency_plug_id`/`emergency_plug2_id` sind DB-interne IDs. Im Backup werden sie als `emergency_plug_ip_ref`/`emergency_plug2_ip_ref` (Plug-IP-Adresse) exportiert und beim Import nach Plug-Import wieder zu IDs aufgelöst. So bleibt ein Restore auf einer anderen Instanz korrekt.

## Rollen

Drei Stufen: `manager` < `power_manager` < `admin`.

- **Manager**: Betrieb — Gäste verwalten & löschen, Maschinen schalten, Berechtigungen vergeben, Wartung erfassen, Raum/Alarm steuern, eigenes Profil bearbeiten
- **Power-Manager**: Konfiguration — zusätzlich Maschinen anlegen/bearbeiten/löschen, Plugs, Automationen, Aushänge, Wartungsintervalle, Kategorien/Standorte, Push-Topics verwalten
- **Admin**: Systemverwaltung — zusätzlich Lab Manager verwalten, Backup/Restore, Einstellungen, In-App-Update

**Rechtetabelle:**

| Bereich / Aktion | Manager | Power-Manager | Admin |
|---|:---:|:---:|:---:|
| Gäste: anzeigen, freischalten, bearbeiten, anlegen, löschen | ✓ | ✓ | ✓ |
| Gäste: Berechtigungen vergeben/entziehen | ✓ | ✓ | ✓ |
| Maschinen: anzeigen, schalten (EIN/AUS) | ✓ | ✓ | ✓ |
| Maschinen: anlegen, bearbeiten, löschen, QR neu generieren | ✗ | ✓ | ✓ |
| Maschinen: CSV-Import, Kategorien, Standorte verwalten | ✗ | ✓ | ✓ |
| Plug-Pool: anzeigen | ✓ | ✓ | ✓ |
| Plug-Pool: anlegen, bearbeiten, löschen, testen, zuweisen | ✗ | ✓ | ✓ |
| Automationen: anzeigen | ✓ | ✓ | ✓ |
| Automationen: anlegen, bearbeiten, löschen | ✗ | ✓ | ✓ |
| Maschinenpflege: Wartung erfassen, Übersicht | ✓ | ✓ | ✓ |
| Maschinenpflege: Intervalle anlegen, bearbeiten, löschen | ✗ | ✓ | ✓ |
| Aushänge: anlegen, bearbeiten, löschen | ✗ | ✓ | ✓ |
| Push-Nachrichten (ntfy): Topics verwalten | ✗ | ✓ | ✓ |
| Raum öffnen/schliessen, Notfall-Alarm | ✓ | ✓ | ✓ |
| Berechtigungen, Log, Statistiken | ✓ | ✓ | ✓ |
| Lab Manager: anlegen, bearbeiten, löschen, Rollen ändern | ✗ | ✗ | ✓ |
| Backup & Restore | ✗ | ✗ | ✓ |
| Einstellungen | ✗ | ✗ | ✓ |
| In-App Update | ✗ | ✗ | ✓ |

**Implementierung:** `require_power_manager` in `services/auth.py` prüft `role in ("admin", "power_manager")`. Frontend-Helpers `_isAdmin()` / `_isPowerPlus()` steuern Button-Sichtbarkeit. ENUM-Migration in `migrate.py` v1.34.

## Berechtigungshistorie (UI)

`GET /permissions/history?guest_id=X` gibt den neuesten `ActivityLog`-Eintrag pro Maschine zurück (Typ `permission_granted` / `permission_revoked`). Der `comment` kommt aus `entry.meta["comment"]`. Das UI zeigt diesen Kommentar in der Berechtigungsmatrix.

Beim Overwrite-Restore: falls `is_blocked` sich ändert, wird ein neuer `ActivityLog`-Eintrag geschrieben, damit die Historie den wiederhergestellten Zustand zeigt.

## Terminologie

- **Aushänge** (nicht "Mitteilungen"): zeitgesteuerte Ankündigungen für Gäste (`announcements`)
- **Push-Nachrichten** (nicht "Benachrichtigungen"): ntfy-basierte Push-Nachrichten
- **Maschinen-Status-Labels**: UI zeigt "Freigegeben"/"Gesperrt"/"In Wartung" statt "Online"/"Offline"/"Wartung" — die gespeicherten Enum-Werte (`online`/`offline`/`maintenance`, `MachineStatus` in `models.py`) sind **unverändert**, nur reine Anzeigetext-Änderung (Filter-Dropdown, Formulare, Hilfetexte in `labmanager.html`). Grund: "Online"/"Offline" implizierte einen Schaltzustand, der für ungeschaltete Inventar-Einträge (z.B. Akku-Schrauber ohne Plug) nicht passt; "Verfügbar"/"Einsatzbereit" wurden verworfen, weil sie mit dem separaten Echtzeit-Belegungsstatus ("In Benutzung") kollidieren können. `_STATUS_MAP` in `routers/machines.py` (CSV-Import) kennt die neuen Begriffe zusätzlich als Synonyme. MCP-Tool `set_machine_status` und der zugehörige `mcp_api.py`-Endpoint nutzen weiterhin die technischen Werte (`online`/`offline`/`maintenance`) als Parameter.

## Bekannte Einschränkungen / Offene Punkte

| Thema | Beschreibung |
|---|---|
| Raum-Session-Hinweis | Wenn Raum bei laufender Session geschlossen wird, läuft Session weiter (by design) — kein UI-Hinweis vorhanden |
| Doppelter Log-Eintrag | `room_close`-Regel mit Zeitplan triggert täglich neu → kosmetisch doppelter Log |
| API Raum-Steuerung | `open_room()` / `close_room()` in `services/room.py` bereit, kein öffentlicher API-Endpoint (z.B. für Home Assistant / Türöffner) |

## `.env` — Umfang bewusst klein halten

Ziel: so wenig wie möglich in `.env`, alles andere über die UI (Einstellungen). Drei Kategorien, siehe Kommentare in `.env.example`:
1. **Bootstrap-Secrets** (`DB_*`, `JWT_SECRET`) — müssen zwingend vor dem ersten Start feststehen, da DB/Backend sonst gar nicht erst starten. Bleiben immer in `.env`.
2. **Infrastruktur** (`HTTP_PORT`/`HTTPS_PORT`, `ALLOWED_ORIGINS`, `TIMEZONE`) — technisch an den Container-Start gebunden (Netzwerk/TZ), ändert sich selten, bleibt in `.env`.
3. **Alles andere** (`NFC_WRITER_URL`, `TS_AUTHKEY`/`TS_HOSTNAME`, `jwt_expire_minutes` u.a.) — wird nur **einmalig** beim allerersten Start als Vorbelegung aus der Umgebung gelesen (siehe `services/system_settings.py` → `get_system_settings()`, `env.<feld>` als Default beim Anlegen der ersten `system_settings`-Zeile), landet danach in der DB und ist ausschliesslich über die UI änderbar. Muss nicht in `.env` stehen.

**Gefundener Bug (2026-07-07):** `install.sh` generierte zusätzlich `BACKUP_EMAIL`/`BACKUP_PASSWORD` in die `.env` — beide Variablen werden nirgends im Code gelesen (kein Treffer in `docker-compose.yml` oder Backend), reiner Totcode aus einer früheren Iteration. Das war die Hauptursache dafür, dass echte Server-`.env`-Dateien von `.env.example` abwichen. Entfernt, `.env.example` gleichzeitig um die vorher fehlenden, aber tatsächlich genutzten Variablen (`ALLOWED_ORIGINS`, `MCP_PORT`) ergänzt und die Kategorie 3 oben als "optional, nicht nötig" kommentiert.

**Wenn ein neues Feature eine neue Konfiguration braucht:** Erst prüfen ob es als Settings-Feld (Kategorie 3) reicht, bevor es in `.env`/`docker-compose.yml` landet — nur wenn der Wert vor dem allerersten Start feststehen muss (Bootstrap/Infra), gehört es wirklich in `.env`.

## Versionierung

- `APP_VERSION` (`backend/app/config.py`) ist eine manuell gepflegte Konstante — wird **nicht** automatisch bei jedem Commit/Migration hochgezählt, sondern von Martin bei Bedarf auf eine neue Release-Nummer gesetzt. Kann daher hinter den Migrations-Versionskommentaren in `migrate.py` (z.B. "v1.41") zurückliegen, das ist normal — beide Nummernkreise sind unabhängig.
- Verwendet in: FastAPI-App-Titel, `GET /api/version`, Backup-Metadaten (`app_version`-Feld), Update-Log-Bundle. Eine Zeile ändern reicht, propagiert überall automatisch.
- `BUILD_NR` dagegen ist automatisch: `git rev-list --count HEAD`, wird beim Start als Env-Var gesetzt (siehe "Häufige Befehle") und im Sidebar-Footer angezeigt.

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

# Update-Watcher Status (Host)
sudo systemctl status spacecaptain-updater

# Update-Log ansehen
tail -f update_trigger/update.log

# Nginx-Config nach Änderungen testen + unterbrechungsfrei neu laden
docker compose exec nginx nginx -t
docker compose exec nginx nginx -s reload
```

## In-App Update

- `POST /api/update/trigger` schreibt `update_trigger/trigger` (Dateiinhalt: ISO-Timestamp)
- `POST /api/update/restart` schreibt `update_trigger/restart` — startet Backend ohne git pull + Rebuild neu
- `GET /api/update/log-bundle` gibt ein ZIP zurück mit System-Info, anonymisierten Settings, DB-Übersicht, aktiven Sessions, Aktivitätslog (letzte 200) und update.log — für Ferndiagnose
- `update_trigger/` ist ein gemeinsames Volume zwischen Backend-Container (`/app/update_trigger`) und Host (`./update_trigger`)
- `spacecaptain-updater.sh` läuft auf dem Host als `systemd`-Service (`spacecaptain-updater.service`), pollt alle 5s, führt je nach Trigger `git pull` + `docker compose up --build backend` (Update) oder nur `docker compose up -d backend` (Restart) aus
- `update_trigger/update.log` — Log aller Aktionen, `st_mtime` dient als `last_triggered`-Timestamp
- `update_trigger/update.status` — letztes Ergebnis: `updated` / `up_to_date` / `restarted` / `error`
- Kein Docker Socket im Container nötig — der Watcher hat nur Dateisystem-Zugriff auf das Trigger-Verzeichnis
- `watcher_ready` im Status: `TRIGGER_DIR.exists()` — zeigt an ob das Volume korrekt gemountet ist

## MCP-Server

Optionaler Service (`mcp_server/`), aktiviert mit `--profile mcp`. Gibt Claude direkten Zugriff auf FabLab-Funktionen ohne Browser.

**Dateien:**
- `mcp_server/main.py` — FastMCP-App mit Tools + `BearerAuthMiddleware`
- `backend/app/routers/mcp_api.py` — interne Backend-Endpunkte (`/api/mcp/*`)

**Auth-Kette (ein einziger Token, kein `.env`-Eintrag nötig):**
```
Claude Code  →  Authorization: Bearer TOKEN  →  MCP-Server (BearerAuthMiddleware prüft)
MCP-Server   →  X-MCP-Key: TOKEN             →  Backend (require_mcp prüft gegen DB)
```

Der Token lebt ausschliesslich in der DB (`system_settings.mcp_api_token`) und wird im UI verwaltet (Einstellungen → Claude MCP). `mcp_server` lädt ihn beim eigenen Start selbst über einen internen Bootstrap-Endpoint (`GET /api/mcp/bootstrap-token` in `mcp_api.py`, `_bootstrap()` in `mcp_server/main.py`) — dieser Endpoint ist von aussen über nginx blockiert (`return 403` in `proxy.conf`), nur containerintern erreichbar. **Keine `MCP_BACKEND_KEY`-Variable in `.env`** — falls das irgendwo referenziert wird (z.B. in älteren Notizen), ist das veraltet.

**Settings-DB:** `mcp_enabled` (Schalter) und `mcp_api_token` (generierter Wert, im UI direkt als Token für die Claude-Code/Desktop-Konfiguration verwendbar). Migration v1.37 in `migrate.py`.

**Neue Tools:** in `mcp_server/main.py` als `@mcp.tool()` + passenden Endpunkt in `mcp_api.py` mit `Depends(require_mcp)`.

**FastMCP-Falle:** `host="0.0.0.0"` und `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)` im Konstruktor zwingend — sonst 403 bei LAN-Hostnamen.

## Nginx-Proxy und Docker-DNS (Vorfall 2026-07-04)

**Vorfall:** Nach einem Update-Rebuild von `backend`/`mcp_server` (neue Docker-interne Container-IP) antwortete `nginx` (Service `nginx`, Container `spacecaptain_proxy`) auf **allen** API-Calls inkl. Login mit 502 "Connection refused" — der Proxy-Container selbst lief seit Tagen unverändert weiter und hatte die alte Backend-IP für die Lebensdauer seines Worker-Prozesses gecached.

**Ursache:** `proxy_pass http://backend:8000;` mit statischem Hostnamen wird von nginx nur **einmal** aufgelöst (beim Start/Reload des Worker-Prozesses), nicht bei jedem Request. Wird der Ziel-Container neu erzeugt (neue IP möglich, auch wenn Docker oft dieselbe IP wiederverwendet), merkt nginx das nicht von selbst.

**Fix** (`nginx/proxy.conf`, `spacecaptain-updater.sh`):
1. `resolver 127.0.0.11 valid=10s;` (Docker-eigener embedded DNS-Server) + `set $backend_upstream http://backend:8000;` statt Literal in `proxy_pass`. Variable statt Literal zwingt nginx, den Hostnamen über den Resolver periodisch neu aufzulösen (max. 10s veraltet) statt ihn dauerhaft zu cachen. Gilt analog für `$frontend_upstream` und `$mcp_upstream`.
2. `spacecaptain-updater.sh`: `nginx` steht jetzt immer in `compose_services()` — wird bei jedem Update/Neustart mit neu gestartet (kein Rebuild nötig, reines Volume-Mount für die Config), damit die Korrektur sofort greift statt erst nach der 10s-TTL.

**Nach Änderungen an `nginx/proxy.conf`:** Kein Rebuild nötig (Volume-Mount, siehe `docker-compose.yml`). Config-Syntax vorab prüfen mit `docker compose exec nginx nginx -t`, dann `docker compose exec nginx nginx -s reload` (unterbrechungsfrei) oder `docker compose restart nginx`.

## Was vermeiden

- `--reload` ohne `--reload-dir /app/app` — WatchFiles überwacht sonst `/app/backups` und löst bei jedem neuen Backup-File einen Reload aus
- Statischen Hostnamen in nginx `proxy_pass` ohne `resolver` + Variable — nginx cached die DNS-Auflösung sonst für die Lebensdauer des Worker-Prozesses, ein Container-Rebuild des Ziels führt zu 502 "Connection refused" bis nginx neu startet (siehe Abschnitt oben)
- Imports aus `backup.py` auf Modulebene in `backup_service.py` — zirkulärer Import
- Neue Settings-Felder nur in `models.py` eintragen — `SettingsOut`/`SettingsUpdate`, den PATCH-Handler (`update_settings()`, setzt jedes Feld einzeln) und Migration vergessen. Schema allein reicht nicht, ohne die explizite `if payload.x is not None: row.x = ...`-Zeile persistiert PATCH das Feld nie.
- Bei `automations.py` Log-Nachrichten `tm.name` verwenden ohne zu prüfen ob `tm` None ist — bei `room_open`/`room_close`/`notify`-Aktionen gibt es keine Ziel-Maschine
- Neue Backup-Sektionen ohne `payload.get("sektion", [])` lesen — bricht ältere Backups
- `emergency_plug_id`/`emergency_plug2_id` direkt in den Settings exportieren — sind DB-interne IDs, müssen als IP-Referenz exportiert und beim Import aufgelöst werden (siehe Notfall-Alarm-Sektion)
- Neue dedizierte Modals (eigenes `<div class="modal-overlay" id="...">`, z.B. `plug-modal`/`battery-modal`) ohne Prüfung von `clientSettings.modal_backdrop_input` schliessen lassen — das generische `openModal()`/`closeModal()` beachtet die Einstellung "Modal bei Klick auf Hintergrund schliessen" bereits, dedizierte Modals müssen das im eigenen `close*Modal(e)`-Handler nachbilden (`if (e && !clientSettings.modal_backdrop_input) return;`), sonst gehen ungespeicherte Formulareingaben bei einem Fehlklick verloren obwohl die Einstellung deaktiviert ist
