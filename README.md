# SpaceCaptain

<p align="center">
  <img src="SpaceCaptain.svg" alt="SpaceCaptain Logo" height="120">
</p>

Webbasiertes Verwaltungssystem für Makerspaces. Gäste werden per QR-Code an Maschinen freigeschaltet, Smart Plugs schalten automatisch ein und aus.

## Features

- **Gästeverwaltung** — Registrierung, Login, Passwort ändern
- **Maschinenverwaltung** — Status, Kategorien, Smart Plug Anbindung
- **Berechtigungs-Matrix** — welcher Gast darf welche Maschine nutzen
- **QR-Code Workflow** — Gast-QR + Maschinen-QR → Plug schaltet ein
- **Leerlauf-Automatik** — Plug schaltet bei Nichtbenutzung automatisch aus
- **Maschinenpflege** — Wartungsintervalle mit Warnungen
- **Aktivitätslog** — vollständiges Audit-Trail
- **Backup / Restore** — JSON-Export und -Import aller Daten
- **Smart Plug Support** — myStrom, Shelly Gen1 und Gen2

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
- Port 80 frei (änderbar via `HTTP_PORT` in `.env`)

### Erstinstallation

```bash
# Repository klonen
git clone git@github.com:drstrangelove52/spacecaptain.git
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
| `BACKUP_EMAIL` | E-Mail des Admin-Accounts für Backups |
| `BACKUP_PASSWORD` | Passwort des Admin-Accounts |

JWT Secret generieren:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

```bash
# Container bauen und starten
docker compose up -d --build

# Logs prüfen
docker compose logs -f spacecaptain_backend
```

### Erster Login

- **URL**: `http://<server-ip>`
- **E-Mail**: `admin@spacecaptain.local`
- **Passwort**: `admin1234`

> **Passwort sofort nach dem ersten Login ändern!**

---

## Update / Rebuild

Das Skript `rebuild.sh` holt die aktuelle Version von Git und startet die Container neu. Alle Daten werden dabei gelöscht.

```bash
# Mit externer .env (z.B. nach Passwortänderung oder Neuinstallation)
sudo bash /opt/spacecaptain/rebuild.sh /pfad/zur/.env

# .env liegt bereits im Projektordner
sudo bash /opt/spacecaptain/rebuild.sh
```

Das Skript führt folgende Schritte aus:
1. `git pull` (als normaler User, SSH-Keys werden berücksichtigt)
2. `.env` kopieren (falls Pfad angegeben)
3. Container stoppen und Volumes löschen (`down -v --rmi all`)
4. Container neu bauen und starten (`up -d --build`)

---

## Automatisches Backup

Das Skript `backup.sh` exportiert alle Daten über die API und speichert sie als komprimierte JSON-Datei.

### Konfiguration in `.env`

```bash
BACKUP_EMAIL=admin@spacecaptain.local   # Admin-Account
BACKUP_PASSWORD=sicheres_passwort

# Optional:
# BACKUP_DIR=/opt/spacecaptain/backups  # Standard: ./backups/
# BACKUP_KEEP=30                        # Anzahl Backups (Standard: 30)
```

### Cron-Job einrichten (täglich 03:00 Uhr)

```bash
crontab -e
```

```
0 3 * * * /opt/spacecaptain/backup.sh >> /opt/spacecaptain/backups/backup.log 2>&1
```

### Backup manuell ausführen

```bash
bash /opt/spacecaptain/backup.sh
```

### Wiederherstellung

Backups können über die Web-Oberfläche unter **Backup & Restore → Import** eingespielt werden, oder per API:

```bash
# Backup entpacken
gunzip -c backups/spacecaptain-backup-2026-01-15_03-00-00.json.gz > restore.json

# Über die API importieren
TOKEN=$(curl -sf -X POST http://localhost/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@spacecaptain.local","password":"..."}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -sf -X POST http://localhost/api/backup/import \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @restore.json
```

> Das Backup enthält Passwort-Hashes und Plug-Tokens — Dateien sicher aufbewahren.

---

## QR-Code Workflow

```
Gast-QR              Maschinen-QR           API prüft         Steckdose
[Login-Token]   →    [Maschinen-Token]  →   Berechtigung  →   EIN / AUS
```

### Setup

1. **Maschine anlegen** — Frontend → Maschinen → Neue Maschine
2. **Gast anlegen** — Frontend → Gäste → Neuer Gast
3. **Berechtigung erteilen** — Frontend → Berechtigungen → Gast × Maschine aktivieren
4. **Gast-QR generieren** — Frontend → QR-System → Gast-QR → ausdrucken oder teilen
5. **Maschinen-QR aufhängen** — Frontend → QR-System → Maschinen-QR → bei der Maschine aufhängen

### Ablauf für den Gast

1. Gast-App öffnen (`http://<server-ip>`) und mit Gast-QR einloggen
2. Maschinen-QR scannen → Berechtigung wird geprüft
3. Steckdose schaltet ein, Session wird protokolliert
4. Nach der Nutzung: **Ausschalten** tippen → Steckdose schaltet aus

---

## Smart Plug Konfiguration

Plugs werden pro Maschine konfiguriert (Frontend → Maschinen → bearbeiten).

### myStrom Switch

| Feld      | Wert |
|-----------|------|
| Plug Typ  | `mystrom` |
| IP        | z.B. `192.168.1.50` |
| Token     | API-Token aus myStrom-App (optional) |
| Extra     | leer |

### Shelly Plug / Plug S (Gen1)

| Feld      | Wert |
|-----------|------|
| Plug Typ  | `shelly` |
| IP        | z.B. `192.168.1.51` |
| Extra     | leer |

### Shelly Plus / Pro (Gen2)

| Feld      | Wert |
|-----------|------|
| Plug Typ  | `shelly` |
| IP        | z.B. `192.168.1.51` |
| Extra     | `gen2` |

### Ohne Smart Plug

| Feld      | Wert |
|-----------|------|
| Plug Typ  | `none` |

Sessions werden trotzdem protokolliert, der Plug wird nur nicht geschaltet.

### Netzwerk-Anforderung

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
docker compose logs -f spacecaptain_backend

# System neu starten (ohne Datenverlust)
docker compose restart

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
├── rebuild.sh                  ← Update-Skript (git pull + Neustart)
├── backup.sh                   ← Backup-Skript mit Rotation
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
│       │   ├── dashboard.py    ← Statistiken
│       │   ├── maintenance.py  ← Wartungsintervalle
│       │   ├── backup.py       ← Export / Import
│       │   └── guest_auth.py   ← Gast-Login, Passwort ändern
│       └── services/
│           ├── auth.py         ← JWT, Passwort-Hashing (bcrypt)
│           ├── plug.py         ← Smart Plug HTTP API
│           ├── session.py      ← Idle-Watcher, Plug-Polling
│           ├── migrate.py      ← Datenbank-Migrationen
│           └── logger.py       ← Aktivitätslog Helper
├── frontend/
│   ├── index.html              ← Gäste-App (PWA)
│   └── labmanager.html         ← Admin / Lab Manager Interface
└── nginx/
    ├── proxy.conf              ← Reverse Proxy (Port 80 → Backend/Frontend)
    └── nginx.conf              ← Frontend Static Files
```

---

## API-Endpunkte

| Methode  | Endpunkt | Beschreibung |
|----------|----------|--------------|
| POST | `/api/auth/login` | Login (JSON: email + password) |
| GET  | `/api/auth/me` | Aktuell eingeloggter User |
| GET  | `/api/dashboard` | Statistiken |
| GET  | `/api/log` | Aktivitätslog |
| GET/POST | `/api/guests` | Gäste verwalten |
| GET/POST | `/api/machines` | Maschinen verwalten |
| GET  | `/api/machines/{id}/qr.png` | QR-Code als PNG |
| GET/POST | `/api/permissions` | Berechtigungs-Matrix |
| POST | `/api/qr/guest-login/{id}` | Gast-Token generieren |
| POST | `/api/qr/scan` | QR-Scan → Plug EIN |
| POST | `/api/qr/release` | Maschine freigeben → Plug AUS |
| POST | `/api/qr/plug/toggle` | Plug manuell schalten (Admin) |
| GET  | `/api/backup/export` | Vollständiger JSON-Export (Admin) |
| POST | `/api/backup/import` | Konfiguration importieren (Admin) |
| GET/POST | `/api/maintenance/intervals` | Wartungsintervalle |
| GET/POST | `/api/maintenance/records` | Wartungsausführungen |

Interaktive Dokumentation: `http://<server-ip>/docs`
