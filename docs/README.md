# SpaceCaptain — Dokumentation

SpaceCaptain ist ein webbasiertes Zugangs- und Verwaltungssystem für Makerspaces. Gäste erhalten per QR-Code Zugang zu Maschinen, smarte Steckdosen schalten den Strom automatisch, und Lab Manager behalten den Überblick über Berechtigungen, Nutzung und Wartung.

---

## Inhaltsverzeichnis

| Dokument | Zielgruppe |
|---|---|
| [Lab-Manager-Handbuch](./labmanager-handbuch.md) | Administratoren und Lab Manager |
| [Gäste-Handbuch](./gast-handbuch.md) | Makerspace-Mitglieder / Gäste |

---

## Systemübersicht

```
Gast (Smartphone)
    │  scannen QR-Code an Maschine
    ▼
┌─────────────────────────────────┐
│        SpaceCaptain Server      │
│  ┌──────────┐  ┌─────────────┐  │
│  │ Frontend │  │  Backend    │  │
│  │ (Nginx)  │  │  (FastAPI)  │  │
│  └──────────┘  └──────┬──────┘  │
│                       │         │
│              ┌────────▼───────┐ │
│              │  MariaDB       │ │
│              │  (Datenbank)   │ │
│              └────────────────┘ │
└─────────────────────────────────┘
    │  HTTP-API
    ▼
Smart Plug (myStrom / Shelly)
    │  Strom EIN / AUS
    ▼
Maschine
```

### Zugänge

| Benutzertyp | URL | Beschreibung |
|---|---|---|
| Gast | `https://ihr-server/` | Mobile Oberfläche für QR-Scan und Maschinenbedienung |
| Lab Manager / Admin | `https://ihr-server/labmanager.html` | Vollständiges Verwaltungs-Dashboard |
| API-Dokumentation | `https://ihr-server/docs` | Interaktive API-Referenz (Swagger UI) |

---

## Schnellstart

### Erstanmeldung Lab Manager
1. `https://ihr-server/labmanager.html` öffnen
2. Mit der bei der Installation erstellten Admin-E-Mail und dem Passwort anmelden
3. Unter **Maschinen** die erste Maschine erfassen
4. Unter **Gäste** den ersten Gast anlegen und Berechtigung erteilen

### Erster Gast
1. Gast-Account unter **Gäste** anlegen
2. Berechtigung für gewünschte Maschinen unter **Berechtigungen** erteilen
3. QR-Code an der Maschine ausdrucken (**QR-System**)
4. Zugangsdaten dem Gast mitteilen

---

## Versionen und Änderungen

Die aktuelle Systemversion ist jederzeit im Sidebar-Footer des Lab-Manager-Dashboards sichtbar.
