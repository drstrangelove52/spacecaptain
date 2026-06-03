# SpaceCaptain — Handover

**Version:** 1.29 · Build 212 · Stand: 2026-06-04

---

## Projektstand

### Fertige Features

| Feature | Version |
|---|---|
| Gäste, Maschinen, Berechtigungen, Plug-Pool (Core) | 1.0+ |
| Smart Plug Steuerung (myStrom, Shelly Gen1/Gen2) | 1.0+ |
| Multi-Plug pro Maschine (junction table `machine_plugs`) | 1.23 |
| Kombiniertes Regelwerk — Automationen + Zeitpläne (power / schedule / room_open / session_active) | 1.27 |
| Raum-Öffnungsstatus: manuell + auto bei erstem Gast-Login | 1.26 |
| Raum-Aktion in Regeln (room_open / room_close als action_type) | 1.29 |
| Gast-Sperre bei geschlossenem Raum | 1.29 |
| `force_off_on_close` Flag pro Maschine | 1.29 |
| CSV-Import für Maschinen (mit Preview-Modal) | 1.24 |
| ntfy Push-Benachrichtigungen (Gäste + Manager-Topics) | 1.13 |
| ntfy Topic-Verwaltung auf Benachrichtigungen-Seite | aktuell |
| Maschinenpflege (Intervalle + freie Wartung) | 1.0+ |
| Warteschlange (Queue) | 1.06 |
| Notfall-Alarm (Display + ntfy + Smart Plug) | 1.11 |
| Backup/Restore (manuell + automatisch) | 1.14 |
| Display-Seite (Kiosk-Modus) | 1.0+ |
| NFC-Writer Integration | 1.0+ |
| Aktivitätslog, Statistiken | 1.0+ |
| BUILD_NR im Sidebar-Footer | 1.24 |
| Design-Konsistenz (Hilfe-Buttons, Toolbar-Buttons, Suchfelder) | aktuell |

### In Arbeit / Kürzlich abgeschlossen

- **Raum-Logik komplett**: Raum öffnen/schliessen, Gast-Sperre, force_off_on_close, Automations-Aktionen
- **Backup v3.0**: Automationsregeln (AutomationRule + RuleCondition) korrekt gesichert
- **Berechtigungsaufteilung**: Lab Manager darf nicht mehr löschen (nur deaktivieren), nur Admin

### Geplant / Offen

- Zeitgesteuertes Öffnen/Schliessen des Raums (via Automationsregel mit Zeitplan-Bedingung — bereits technisch möglich, nur noch konfigurieren)
- API-Zugang für Raum öffnen/schliessen (z.B. Türöffner, Home Assistant) — technisch bereit, kein Frontend-Workflow nötig
- OR-Verknüpfung in Automationsbedingungen (bewusst zurückgestellt)

---

## Letzte wichtige Änderungen

### v1.29 — Raum-Zugang + Raumschluss-Logik
**Warum:** Gäste durften Maschinen auch bei geschlossenem Raum nutzen (inkonsistent mit Raum-Konzept). Beim Schliessen wurden alle Maschinen ausgeschaltet, aber 3D-Drucker sollen über Nacht laufen können.

**Lösung:** Invertierte Logik — beim Schliessen läuft alles weiter, *ausser* Maschinen mit `force_off_on_close=True` (z.B. Kaffeemaschine, Lötstation).

### Automationen-Refactoring (v1.27)
**Warum:** Alte „Automationen" (nur Leistungs-Trigger) und neue „Zeitpläne" waren getrennte Konzepte mit separaten Tabellen und Watchers. Unübersichtlich und nicht kombinierbar.

**Lösung:** Einheitliches Regelwerk — eine Regel, beliebige AND-verknüpfte Bedingungen (power, schedule, room_open, session_active), ein Watcher (`rule_watcher.py`).

### ntfy Topics auf Benachrichtigungen-Seite
**Warum:** Topics waren in den Einstellungen versteckt, die Benachrichtigungen-Seite war read-only. Verwirrend.

---

## Wichtige Designentscheide

| Entscheid | Begründung |
|---|---|
| `force_off_on_close` statt „alles aus bei Raumschluss" | 3D-Drucker laufen über Nacht — explizites Flag pro Gerät ist sicherer als Whitelist |
| Automationsbedingungen AND-verknüpft | OR würde zwei separate Regeln ersetzen, deutlich einfachere UX |
| Raum-Status nur informativ für bestehende Sessions | Laufende Maschinen-Sessions werden nicht unterbrochen wenn Raum schliesst |
| `session_active` + `off_delay_sec` statt `inactivity`-Trigger | Deckt denselben Use-Case ohne Extra-Typ: Lüftung läuft 30min nach letzter Session |
| Lab Manager darf deaktivieren, nicht löschen | Verhindert versehentlichen Datenverlust; Gast-History bleibt erhalten |
| ntfy Topics ohne `key`-Feld | Feld war nie funktional genutzt, nur verwirrend |
| Backup v3.0: AutomationRule statt MachineAutomation | Alter Typ war Legacy nach Refactoring in v1.27 |

---

## Bekannte Bugs / Offene Fragen

| # | Beschreibung | Status |
|---|---|---|
| 1 | Wenn Raum bei bereits laufender Maschinen-Session geschlossen wird, läuft die Session weiter (by design) — Gast kann die Maschine aber ausschalten | By design, evtl. Hinweis im UI |
| 2 | `BUILD_NR` muss bei jedem Container-Start mitgegeben werden: `BUILD_NR=$(git rev-list --count HEAD) docker compose up -d` | Dokumentiert, kein Auto-Update |
| 3 | Automationsregel mit `room_close` action und Zeitplan-Bedingung: wenn der Zeitplan-Watcher die Regel am nächsten Tag erneut triggert, wird der Raum nochmals geschlossen (idempotent, aber doppelter Log-Eintrag) | Kosmetisch |
| 4 | Gast-App (index.html): wenn Raum geschlossen, erhält Gast HTTP 403 — Fehlermeldung in der App sollte „Raum ist geschlossen" zeigen (aktuell generische Fehlermeldung) | TODO |

---

## Wichtige Dateien

```
backend/app/
  models.py              — ORM: alle Tabellen inkl. AutomationRule, RuleCondition, Machine (force_off_on_close)
  services/migrate.py    — Migrationen (idempotent, laufen bei jedem Start)
  services/rule_watcher.py — Kombinierter Automations-Watcher (10s Intervall)
  services/room.py       — open_room() / close_room() mit force_off-Logik
  routers/automations.py — Regelwerk CRUD (action_type: machine|room_open|room_close)
  routers/guest_auth.py  — Gast-Zugang inkl. Raum-Sperre
  routers/backup.py      — Backup v3.0 (inkl. AutomationRule + RuleCondition)

frontend/
  labmanager.html        — Komplette Admin-UI (single file, kein Framework)
  index.html             — Gäste-App
  display.html           — Kiosk/Display-Seite
```

---

## Starten

```bash
BUILD_NR=$(git rev-list --count HEAD) docker compose up -d
```
