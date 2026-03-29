# SpaceCaptain

<p align="center">
  <img src="SpaceCaptain.svg" alt="SpaceCaptain Logo" height="120">
</p>

SpaceCaptain ist das Verwaltungssystem für deinen Makerspace — Berechtigungen, Maschinensteuerung per Smart Plug und Maschinenpflege in einer App.

Fragen oder Ideen? → [GitHub Issue erstellen](https://github.com/drstrangelove52/spacecaptain/issues) &nbsp;·&nbsp; Projekt nützlich? → [Ko-fi Spende](https://ko-fi.com/pobli) ☕

---

## Features

- **Gästeverwaltung** — Gäste anlegen, Selbstregistrierung mit Freischaltung, Login per Passwort oder Token-Link
- **Maschinenverwaltung** — Maschinen mit Kategorien, Standort, Smart Plug, Leerlauf-Automatik und Betriebsstunden-Tracking
- **Berechtigungs-Matrix** — Zugriffsrechte pro Gast und Maschine mit Sperren, Kommentaren und Verlauf
- **QR-Code & NFC-Tags** — Maschinenfreigabe per QR- oder NFC-Scan mit dem Smartphone
- **Leerlauf-Automatik** — Plug schaltet automatisch aus wenn die Maschine den konfigurierten Verbrauchsschwellwert unterschreitet
- **Maschinenpflege** — Wartungsintervalle nach Betriebsstunden oder Kalendertagen mit Vorwarnung, Dokumentation und Verlauf
- **Warteliste** — Gäste reihen sich ein und werden per Push benachrichtigt wenn die Maschine frei wird
- **Push-Benachrichtigungen** — ntfy-Integration mit persönlichem Topic pro Gast und konfigurierbaren System-Topics für Lab Manager
- **Notfall-Alarm** — Auslösung per physischem Knopf, schaltet Sirene und Blinklicht ein, benachrichtigt Lab Manager per Push
- **Aktivitätslog** — vollständiges Audit-Trail inkl. IP-Adressen
- **Backup / Restore** — automatisches tägliches oder manuelles JSON-Backup aller Daten, Import mit Overwrite- oder Merge-Modus
- **Smart Plug Support** — myStrom, Shelly Gen1, Shelly Gen2/Gen3/Gen4

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
| `TIMEZONE` | Zeitzone des Servers (z.B. `Europe/Zurich`, `Europe/Berlin`) |

JWT Secret generieren:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

```bash
# TLS-Zertifikat erstellen (Pflicht — ohne Zertifikat startet Nginx nicht)
bash gencert.sh <server-ip>

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

Das Skript `gencert.sh` erstellt ein selbstsigniertes Zertifikat:

```bash
bash gencert.sh 192.168.1.100   # IP-Adresse des Servers
```

Das Zertifikat wird in `certs/cert.pem` und `certs/key.pem` abgelegt (gültig 10 Jahre). Danach die Container neu starten:

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
git pull
docker compose up -d --build backend
```

DB-Migrationen laufen automatisch beim Backend-Start.

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

## Lizenz

© 2026 Martin Nigg — veröffentlicht unter der **[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)**.

Nutzung, Weitergabe und Modifikation sind für **nicht-kommerzielle Zwecke** frei erlaubt. Jede kommerzielle Nutzung ist ohne ausdrückliche Genehmigung untersagt.

---

## Kontakt & Unterstützung

Fragen, Ideen oder Fehler gerne als [GitHub Issue](https://github.com/drstrangelove52/spacecaptain/issues) melden.

SpaceCaptain wird in der Freizeit entwickelt — über eine kleine [Ko-fi Spende](https://ko-fi.com/pobli) freue ich mich sehr ☕
