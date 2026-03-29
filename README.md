# SpaceCaptain

<p align="center">
  <img src="SpaceCaptain.svg" alt="SpaceCaptain Logo" height="120">
</p>

Webbasiertes Verwaltungssystem für Makerspaces. Gäste werden per QR-Code an Maschinen freigeschaltet, Smart Plugs schalten automatisch ein und aus.

Fragen oder Ideen? → [GitHub Issue erstellen](https://github.com/drstrangelove52/spacecaptain/issues) &nbsp;·&nbsp; Projekt nützlich? → [Ko-fi Spende](https://ko-fi.com/pobli) ☕

---

## Features

- **Gästeverwaltung** — Registrierung, Login, Passwort ändern
- **Maschinenverwaltung** — Status, Kategorien, Smart Plug Anbindung
- **Berechtigungs-Matrix** — welcher Gast darf welche Maschine nutzen
- **QR-Code & NFC Workflow** — Gast scannt Maschinen-QR oder tippt NFC-Tag → Plug schaltet ein
- **Leerlauf-Automatik** — Plug schaltet bei Nichtbenutzung automatisch aus
- **Maschinenpflege** — Wartungsintervalle mit Warnungen
- **Warteliste** — Gäste stellen sich in die Warteschlange, ntfy-Benachrichtigung wenn Maschine frei wird
- **Push-Benachrichtigungen** — ntfy-Integration für System-Events und persönliche Gast-Topics
- **Notfall-Alarm** — Auslöser startet Alarm, schaltet Plugs aus, sendet Push, Quittierung mit Kommentarpflicht
- **Aktivitätslog** — vollständiges Audit-Trail inkl. IP-Adressen
- **Backup / Restore** — JSON-Export und -Import aller Daten (automatisch täglich oder manuell)
- **Smart Plug Support** — myStrom, Shelly Gen1, Shelly Gen2/Gen3/Gen4

## Stack

| Komponente | Technologie |
|------------|-------------|
| Backend    | Python 3.12 + FastAPI |
| Datenbank  | MariaDB 11 |
| Frontend   | HTML / JS (Vanilla, keine Frameworks) |
| Proxy      | Nginx |
| Container  | Docker Compose |

---

## Installation

### Voraussetzungen

- Docker und Docker Compose
- Git
- Port 80 und 443 frei (änderbar via `HTTP_PORT` / `HTTPS_PORT` in `.env`)

### Erstinstallation

```bash
# Repository klonen
git clone https://github.com/drstrangelove52/spacecaptain.git
cd spacecaptain

# Umgebungsvariablen konfigurieren
cp .env.example .env
nano .env
```

Mindestens anpassen:

| Variable | Beschreibung |
|----------|-------------|
| `DB_ROOT_PASSWORD` | Sicheres Root-Passwort für MariaDB |
| `DB_PASSWORD` | Datenbankpasswort für die App |
| `JWT_SECRET` | Zufälliger String (mind. 32 Zeichen) |
| `ALLOWED_ORIGINS` | Erlaubte CORS-Origins (kommagetrennt, z.B. `https://192.168.1.100`) |
| `TIMEZONE` | Zeitzone des Servers (z.B. `Europe/Zurich`, `Europe/Berlin`) |

JWT Secret generieren:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

```bash
# Container bauen und starten
docker compose up -d --build

# Logs prüfen
docker compose logs -f backend
```

### Erster Login

- **URL**: `https://<server-ip>/labmanager`
- **E-Mail**: `admin@spacecaptain.local`
- **Passwort**: `admin1234`

> **Passwort sofort nach dem ersten Login ändern!**

---

## HTTPS einrichten

Nginx ist als Reverse Proxy konfiguriert und unterstützt TLS. Das Skript `gencert.sh` erstellt ein selbstsigniertes Zertifikat:

```bash
bash gencert.sh <hostname-oder-ip>

# Beispiele:
bash gencert.sh spacecaptain.local
bash gencert.sh 192.168.1.100
```

Das Zertifikat wird in `certs/cert.pem` und `certs/key.pem` abgelegt (gültig 10 Jahre). Danach `ALLOWED_ORIGINS` in der `.env` auf `https://` umstellen und die Container neu starten:

```bash
docker compose up -d
```

Für ein offizielles Zertifikat (z.B. Let's Encrypt) einfach `cert.pem` und `key.pem` in `certs/` ersetzen und Nginx neu laden:

```bash
docker exec spacecaptain_proxy nginx -s reload
```

---

## Update

```bash
# Code holen
git pull

# Backend neu starten (Migrationen laufen automatisch beim Start)
docker compose up -d --build backend
```

Der Frontend-Code (HTML/JS) ist als Volume eingebunden und wird durch `git pull` sofort aktualisiert — kein Neustart nötig. DB-Migrationen laufen automatisch beim Backend-Start.

---

## Backup & Restore

### Automatisches Backup

SpaceCaptain sichert die Daten täglich automatisch als JSON-Datei. Konfiguration unter **Einstellungen → Automatisches Backup**:

- **Uhrzeit** — Zeitpunkt der täglichen Sicherung (Standard: 03:00)
- **Aufbewahrung** — Anzahl Backups (Standard: 30 ≈ 1 Monat)

Das Backup-Verzeichnis wird via `BACKUP_DIR` in der `.env` konfiguriert (Standard: `./backups`). NFS-Shares werden unterstützt — einfach den gemounteten Pfad eintragen.

### Manuelles Backup

Sidebar → **Backup** → «Jetzt sichern», oder über die API:

```bash
TOKEN=$(curl -sf -X POST http://localhost/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@spacecaptain.local","password":"..."}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -sf -X GET http://localhost/api/backup/export \
  -H "Authorization: Bearer $TOKEN" -o backup.json
```

### Wiederherstellung

Backups können über die Web-Oberfläche unter **Backup → Restore** eingespielt werden.

> Das Backup enthält Passwort-Hashes und Plug-Tokens — Dateien sicher aufbewahren.

---

## QR-Code & NFC Workflow

Jede Maschine hat einen eindeutigen Token — hinterlegt als QR-Code-Aufkleber oder auf einem NFC-Tag. Der Gast identifiziert sich über die Gäste-App, die API prüft die Berechtigung und schaltet den Plug.

```
Gast (eingeloggt)    Maschinen-QR / NFC-Tag     API prüft         Steckdose
[Session-Token]  →   [Maschinen-Token]       →  Berechtigung  →   EIN / AUS
```

### Setup

1. **Maschine anlegen** — Sidebar → Maschinen → Neue Maschine
2. **Gast anlegen** — Sidebar → Gäste → Neuer Gast
3. **Berechtigung erteilen** — Sidebar → Berechtigungen → Gast × Maschine aktivieren
4. **QR-Code aufhängen** — Sidebar → Maschinen → QR-Code drucken und bei der Maschine befestigen
5. **Optional: NFC-Tag beschreiben** — NFC-Writer (`/nfc-setup`) mit ESP32 + PN532 einrichten, Tag an die Maschine kleben

### Ablauf für den Gast

1. Gäste-App öffnen (`https://<server-ip>`) und einloggen
2. Maschinen-QR mit der Kamera scannen **oder** NFC-Tag antippen
3. Berechtigung wird geprüft — Steckdose schaltet ein, Session wird protokolliert
4. Nach der Nutzung: **Ausschalten** tippen → Steckdose schaltet aus

### QR vs. NFC

| | QR-Code | NFC-Tag |
|---|---|---|
| Hardware | keiner (Smartphone-Kamera) | ESP32 + PN532 (NFC-Writer) |
| Aufwand | minimal | einmalige Einrichtung des Writers |
| Vorteil | sofort einsatzbereit | schneller (antippen statt scannen) |

---

## Smart Plug Konfiguration

Plugs werden pro Maschine konfiguriert (Sidebar → Maschinen → bearbeiten).

### myStrom Switch

| Feld      | Wert |
|-----------|------|
| Plug Typ  | `mystrom` |
| IP        | z.B. `192.168.1.50` |
| Token     | API-Token aus myStrom-App (optional) |

### Shelly Plug / Plug S (Gen1)

| Feld      | Wert |
|-----------|------|
| Plug Typ  | `shelly` |
| IP        | z.B. `192.168.1.51` |
| Passwort  | Nur wenn HTTP-Auth aktiviert: `user:passwort` |

### Shelly Plus / Pro / Mini (Gen2/Gen3/Gen4)

| Feld      | Wert |
|-----------|------|
| Plug Typ  | `shelly_gen2` |
| IP        | z.B. `192.168.1.52` |
| Passwort  | Nur wenn HTTP-Auth aktiviert: `user:passwort` |

### Ohne Smart Plug

| Feld      | Wert |
|-----------|------|
| Plug Typ  | `none` |

Sessions werden trotzdem protokolliert, der Plug wird nur nicht geschaltet.

### Netzwerk-Empfehlung

Das Backend muss die Plugs direkt per HTTP erreichen können. Empfohlen: Plugs in einem separaten IoT-VLAN, das nur vom SpaceCaptain-Server erreichbar ist.

```
Gäste-WLAN  →  SpaceCaptain-Server  →  IoT-VLAN (Plugs)
Gäste-WLAN  →  IoT-VLAN             →  GESPERRT
Internet    →  IoT-VLAN             →  GESPERRT
```

---

## Nützliche Befehle

```bash
# Status aller Container
docker compose ps

# Logs verfolgen
docker compose logs -f backend

# Backend neu starten
docker compose restart backend

# In den Backend-Container einloggen
docker exec -it spacecaptain_backend bash

# Datenbank-Shell öffnen
docker exec -it spacecaptain_db mariadb -u spacecaptain -p spacecaptain

# Kompletten Neustart (⚠️ löscht alle Daten!)
docker compose down -v
docker compose up -d --build
```

---

## Projektstruktur

```
spacecaptain/
├── docker-compose.yml          ← Container-Orchestrierung
├── .env.example                ← Konfigurationsvorlage
├── .env                        ← lokale Konfiguration (nicht im Git)
├── gencert.sh                  ← Selbstsigniertes TLS-Zertifikat generieren
├── db/
│   └── init.sql                ← Datenbankschema + Default-Admin
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             ← FastAPI App, Lifespan
│       ├── config.py           ← Einstellungen aus Umgebungsvariablen
│       ├── database.py         ← Async SQLAlchemy Engine
│       ├── models.py           ← ORM-Modelle
│       ├── schemas.py          ← Pydantic Request/Response Schemas
│       ├── routers/
│       │   ├── auth.py         ← Login, JWT
│       │   ├── users.py        ← Lab Manager CRUD
│       │   ├── guests.py       ← Gäste CRUD
│       │   ├── machines.py     ← Maschinen + QR-Code PNG
│       │   ├── permissions.py  ← Berechtigungs-Matrix
│       │   ├── qr.py           ← QR-Scan, Plug-Steuerung
│       │   ├── dashboard.py    ← Statistiken + Aktivitätslog
│       │   ├── maintenance.py  ← Wartungsintervalle
│       │   ├── queue.py        ← Warteliste
│       │   ├── ntfy_topics.py  ← System-ntfy-Topics
│       │   ├── emergency.py    ← Notfall-Alarm
│       │   ├── settings.py     ← Systemeinstellungen
│       │   ├── backup.py       ← Export / Import
│       │   └── guest_auth.py   ← Gast-Login, Passwort ändern
│       └── services/
│           ├── auth.py         ← JWT, Passwort-Hashing (bcrypt)
│           ├── plug.py         ← Smart Plug HTTP API
│           ├── session.py      ← Idle-Watcher, Plug-Polling
│           ├── ntfy.py         ← Push-Benachrichtigungen (ntfy)
│           ├── queue_service.py← Wartelisten-Logik, ntfy-Benachrichtigung
│           ├── backup_service.py← Auto-Backup, Cleanup
│           ├── migrate.py      ← Datenbank-Migrationen
│           └── logger.py       ← Aktivitätslog Helper
├── frontend/
│   ├── index.html              ← Gäste-App (PWA)
│   └── labmanager.html         ← Admin / Lab Manager Interface
├── nginx/
│   ├── proxy.conf              ← Reverse Proxy (Port 80/443 → Backend/Frontend)
│   └── nginx.conf              ← Frontend Static Files
└── certs/
    ├── cert.pem                ← TLS-Zertifikat (nicht im Git)
    └── key.pem                 ← TLS-Schlüssel (nicht im Git)
```

---

## API-Endpunkte

| Methode  | Endpunkt | Beschreibung |
|----------|----------|--------------|
| POST | `/api/auth/login` | Login (JSON: email + password) |
| GET  | `/api/auth/me` | Aktuell eingeloggter User |
| GET  | `/api/dashboard` | Operative Metriken (Sessions, Registrierungen, Wartung) |
| GET  | `/api/log` | Aktivitätslog (Filter: guest_id, machine_id, type, date_from, date_to, search) |
| GET/POST | `/api/guests` | Gäste verwalten |
| POST | `/api/guests/register` | Gast-Selbstregistrierung (öffentlich) |
| POST | `/api/guests/{id}/approve` | Registrierung freischalten |
| GET/POST | `/api/machines` | Maschinen verwalten |
| GET  | `/api/machines/{id}/qr.png` | QR-Code als PNG |
| GET/POST | `/api/permissions` | Berechtigungs-Matrix |
| POST | `/api/qr/scan` | QR-Scan → Plug EIN |
| POST | `/api/qr/release` | Maschine freigeben → Plug AUS |
| GET/POST | `/api/queue` | Warteliste verwalten |
| GET/POST | `/api/ntfy-topics` | System-ntfy-Topics verwalten |
| GET  | `/api/emergency/status` | Notfall-Status abfragen |
| POST | `/api/emergency/trigger` | Notfall-Alarm auslösen (Header: X-Emergency-Token) |
| POST | `/api/emergency/cancel` | Notfall-Alarm quittieren (JWT, Pflichtkommentar) |
| GET/PATCH | `/api/settings` | Systemeinstellungen lesen/schreiben |
| GET  | `/api/backup/export` | Vollständiger JSON-Export |
| POST | `/api/backup/import` | Konfiguration importieren |
| GET/POST | `/api/maintenance/intervals` | Wartungsintervalle |
| GET/POST | `/api/maintenance/records` | Wartungsausführungen |

Interaktive Dokumentation: `http://<server-ip>/docs`

---

## Lizenz

© 2026 Martin Nigg — veröffentlicht unter der **[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)**.

Nutzung, Weitergabe und Modifikation sind für **nicht-kommerzielle Zwecke** frei erlaubt. Jede kommerzielle Nutzung ist ohne ausdrückliche Genehmigung untersagt.

---

## Kontakt & Unterstützung

Fragen, Ideen oder Fehler gerne als [GitHub Issue](https://github.com/drstrangelove52/spacecaptain/issues) melden.

SpaceCaptain wird in der Freizeit entwickelt — über eine kleine [Ko-fi Spende](https://ko-fi.com/pobli) freue ich mich sehr ☕
