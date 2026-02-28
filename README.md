# ⚡ MakerSpace Verwaltungssystem

Webbasiertes Verwaltungstool für Makerspaces mit:
- **Gästeverwaltung** mit QR-Code Freischaltung
- **Lab Manager** Verwaltung mit JWT-Login
- **Maschinenübersicht** mit Smart Plug Anbindung
- **Berechtigungs-Matrix** (Gast × Maschine)
- **Aktivitätslog**
- **Smart Plug Support**: myStrom, Shelly, Tasmota, IKEA INSPELNING

---

## Stack

| Komponente | Technologie |
|-----------|-------------|
| Backend   | Python 3.12 + FastAPI |
| Datenbank | MariaDB 11 |
| Frontend  | HTML/JS (Vanilla) |
| Proxy     | Nginx |
| Container | Docker Compose |

---

## Schnellstart

### 1. Voraussetzungen
- Docker & Docker Compose installiert
- Port 80 frei (änderbar via `.env`)

### 2. Setup

```bash
# Repository klonen / entpacken
cd makerspace

# Umgebungsvariablen konfigurieren
cp .env.example .env
nano .env   # Passwörter & JWT_SECRET anpassen!

# Starten
docker compose up -d

# Logs beobachten
docker compose logs -f backend
```

### 3. Zugriff

- **Frontend**: http://localhost
- **API Docs**: http://localhost/docs
- **Standard Login**: `admin@makerspace.local` / `admin1234`

> ⚠️ **Passwort sofort nach dem ersten Login ändern!**

---

## QR-Code Workflow

```
Gast erhält QR      Scannt Maschinen-QR     API prüft         Steckdose EIN
[Gast-Token QR]  →  [Maschinen-Token QR]  →  Berechtigung  →  myStrom/Shelly/Tasmota
```

### Gast-QR erstellen
1. Im Frontend → QR-System → "Gast-QR generieren"
2. QR-Code ausdrucken oder per App teilen
3. Gast speichert QR auf seinem Smartphone

### Maschinen-QR aufhängen
1. Im Frontend → QR-System → "Maschinen-QR drucken"
2. QR-Code bei der Maschine aufhängen

### Scan-Endpunkt (für mobile App / PWA)
```
POST /api/qr/scan
{
  "guest_token": "<token-aus-gast-qr>",
  "machine_qr": "<token-aus-maschinen-qr>"
}
```

---

## Smart Plug Konfiguration

### myStrom Switch (Schweiz 🇨🇭)
| Feld       | Wert |
|-----------|------|
| Plug Typ  | `mystrom` |
| IP        | z.B. `192.168.1.50` |
| Extra     | leer |

### Shelly Plug / Plug S (Gen1)
| Feld       | Wert |
|-----------|------|
| Plug Typ  | `shelly` |
| IP        | z.B. `192.168.1.51` |
| Extra     | leer |

### Shelly Plus / Pro (Gen2)
| Feld       | Wert |
|-----------|------|
| Plug Typ  | `shelly` |
| IP        | z.B. `192.168.1.51` |
| Extra     | `gen2` |

### IKEA INSPELNING (mit Tasmota)
Flash das IKEA Plug mit Tasmota, dann:
| Feld       | Wert |
|-----------|------|
| Plug Typ  | `inspelning` |
| IP        | z.B. `192.168.1.52` |
| Extra     | leer (oder Kanal-Nummer) |

### IKEA INSPELNING (über Zigbee2MQTT)
Benötigt zigbee2mqtt mit REST-Companion:
| Feld       | Wert |
|-----------|------|
| Plug Typ  | `inspelning` |
| IP        | `<zigbee2mqtt-host>:port` |
| Extra     | `zigbee2mqtt` |

### Tasmota (beliebige Hardware)
| Feld       | Wert |
|-----------|------|
| Plug Typ  | `tasmota` |
| IP        | z.B. `192.168.1.53` |
| Extra     | leer (oder `2` für Kanal 2) |

---

## Netzwerk-Voraussetzung

Der **Docker-Container (Backend)** muss die Smart Plugs direkt erreichen können.

**Option A** — Plugs im selben Netzwerk wie der Docker-Host:
```yaml
# docker-compose.yml → backend service:
network_mode: host  # Linux only
```

**Option B** — Netzwerk-Route über Docker:
```yaml
networks:
  makerspace_net:
    driver: bridge
    ipam:
      config:
        - subnet: 192.168.100.0/24
```

**Option C** — Nginx als Reverse-Proxy für Plug-Requests (empfohlen für Produktion)

---

## Nützliche Befehle

```bash
# System neu starten
docker compose restart

# Datenbank-Backup
docker exec makerspace_db mysqldump -u root -p makerspace > backup.sql

# Logs anzeigen
docker compose logs backend --tail=100 -f

# In Backend-Container einloggen
docker exec -it makerspace_backend bash

# Datenbank zurücksetzen (⚠️ löscht alle Daten!)
docker compose down -v
docker compose up -d
```

---

## Projektstruktur

```
makerspace/
├── docker-compose.yml
├── .env.example
├── .env                    ← lokal, nicht ins Git!
├── db/
│   └── init.sql            ← Datenbankschema + Default-Admin
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py         ← FastAPI App
│       ├── config.py       ← Einstellungen
│       ├── database.py     ← DB Session
│       ├── models.py       ← SQLAlchemy Models
│       ├── schemas.py      ← Pydantic Schemas
│       ├── routers/
│       │   ├── auth.py     ← Login/JWT
│       │   ├── users.py    ← Lab Manager CRUD
│       │   ├── guests.py   ← Gäste CRUD
│       │   ├── machines.py ← Maschinen + QR PNG
│       │   ├── permissions.py
│       │   ├── qr.py       ← Scan + Plug-Steuerung
│       │   └── dashboard.py
│       └── services/
│           ├── auth.py     ← JWT Helper
│           ├── plug.py     ← Smart Plug API (myStrom/Shelly/Tasmota)
│           └── logger.py   ← Aktivitätslog Helper
├── frontend/
│   └── index.html          ← Single-Page App
└── nginx/
    ├── proxy.conf          ← Reverse Proxy (Port 80)
    └── nginx.conf          ← Frontend Static
```

---

## API Endpunkte (Übersicht)

| Method | Endpoint | Beschreibung |
|--------|----------|--------------|
| POST | `/api/auth/login` | JWT Login |
| GET | `/api/auth/me` | Aktueller User |
| GET | `/api/dashboard` | Statistiken |
| GET/POST | `/api/guests` | Gäste |
| GET/POST | `/api/machines` | Maschinen |
| GET `…/qr.png` | `/api/machines/{id}/qr.png` | QR-Code PNG |
| POST | `/api/permissions/grant` | Berechtigung erteilen |
| POST | `/api/permissions/bulk` | Matrix speichern |
| POST | `/api/qr/guest-login/{id}` | Gast-Token generieren |
| **POST** | **`/api/qr/scan`** | **QR-Scan + Plug EIN** |
| POST | `/api/qr/release` | Maschine freigeben (Plug AUS) |
| POST | `/api/qr/plug/toggle` | Manuell schalten |
| GET | `/api/log` | Aktivitätslog |

Vollständige Dokumentation: **http://localhost/docs**


## Sicherheitshinweise

### Smart Plug Netzwerk-Isolation
Die myStrom und Shelly Plugs sollten in einem separaten IoT-VLAN betrieben werden, das nur vom MakerSpace-Server (Backend-Container) erreichbar ist — nicht direkt vom Gäste-WLAN oder Internet.

Empfohlene Firewall-Regel:
- IoT-VLAN → Internet: gesperrt
- IoT-VLAN → MakerSpace-Server: erlaubt (Port 80)
- Gäste-WLAN → IoT-VLAN: gesperrt

So können Plugs nur über die authentifizierte API angesprochen werden, nie direkt vom Browser.
