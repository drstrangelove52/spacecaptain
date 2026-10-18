# Konzept: Modul «Inventar & Lagerorte»

Status: **Etappe 1 umgesetzt** (2026-10-18, Branch `feature/inventar-modul`, noch nicht auf Dev
ausgerollt). Etappen 2–5 offen. Backend: `models_inventory.py`, `services/inventory.py`,
`routers/inventory.py`; Oberfläche: `frontend/modules/inventory.js` (Modul im LabManager); Tests: `backend/tests` (`cd backend && pytest`).

Planungsebene im Second Brain: `03 Bereiche/SpaceCaptain/Inventar-Modul.md`.

## 1. Ziel

Zwei Probleme im Makerspace lösen:

1. **Neue Gäste finden Werkzeug und Maschinen nicht.**
2. **Werkzeug landet im falschen Schrank.**

Dazu bekommt jedes Ding einen **eindeutigen, aufgedruckten Lagerort-Code**, es gibt eine
**Suche** («Wo ist der Akkuschrauber?») und einen **Bauplan** mit Bereichen, Schränken
und Maschinen. Gegen Unordnung helfen vor allem Schattenbretter und Soll-Listen pro Fach;
das Modul liefert dafür die Listen und Etiketten.

Randbedingungen:

- Die Nutzer sind **wenig diszipliniert**. Das System darf nichts voraussetzen, was
  jeder bei jedem Wegräumen tun muss (kein Scan-Zwang).
- Der **Standort des Makerspace ist im Umbruch** (Umzug). Codes dürfen nicht vom
  Raumlayout abhängen.
- SpaceCaptain bleibt stabil. Das Modul ist **additiv**: neue Dateien, neue Tabellen,
  per Einstellung abschaltbar.

## 1a. Ausgangslage und frühere Entscheidung

Am 2026-07-04 wurde für das **Maschineninventar** bewusst *keine* eigene
«Inventory Item»-Entität eingeführt: Maschinen ohne Plug sind einfache
`Machine`-Einträge (ein Modell, eine Liste, kein Migrationsaufwand bei späterem Nachrüsten
eines Plugs). Diese Entscheidung bleibt **für Maschinen unverändert**.

Neu ist der Bedarf an einer **grossen Menge Werkzeug und Kleingerät**
(geschätzt Hunderte Einträge, 6–8 Schränke). Diese in `machines` zu führen würde
Berechtigungsmatrix, Wartungsübersicht, Dashboard, Maschinen-CSV und Display belasten
(Gäste bekommen pro Maschine eine Freigabe). Darum bekommt Werkzeug eine eigene, schlanke
Tabelle, teilt sich aber Bereiche, Plan und Suche mit den Maschinen.

Stand der Daten (Produktion, 2026-10): 19 Maschinen, der **Standort ist fast überall
leer**, Kaufdatum und Neuwert nur bei einer Maschine gepflegt. Es gibt also kaum Altlasten;
die Struktur kann sauber aufgebaut werden.

## 2. Entscheidungen (mit Martin abgestimmt)

| # | Entscheidung |
|---|---|
| 1 | Modul in SpaceCaptain: **eigene Dateien, aber als Seite im LabManager** (`modules/inventory.js`), gleiches Backend, gleiche Anmeldung, gleiche Rollen |
| 2 | **Zwei Objektarten, ein gemeinsamer Plan und eine gemeinsame Suche:** Maschinen bleiben in `machines`, Werkzeug/Kleingerät kommt in eine neue Tabelle |
| 3 | `machine_locations` wird zur **Bereichs-Tabelle** erweitert (keine zweite Standortliste) |
| 4 | Maschinen tragen **keinen aufgedruckten Lagerort-Code**, sondern Bereich + Platz auf dem Plan. Sie können den Bereich wechseln |
| 5 | **Die 0 bedeutet «nicht unterteilt oder noch nicht festgelegt»** auf jeder Stufe (`S0`, `E0`, `P0`). Jeder Code hat dieselbe Form, es gibt keine `NULL`-Plätze |
| 6 | **Tische und Werkbänke** sind normale Möbel (`kind = tisch`), Maschinen können optional «auf» einem Möbel stehen |

## 3. Begriffe und Code-Schema

```
<Bereich>-S<Schrank>-E<Ebene>-P<Position>      Beispiel: EL-S2-E3-P4
```

| Stufe | Bedeutung | Zählregel |
|---|---|---|
| **Bereich** | Fachgebiet (Holz, Elektronik, Laser …), 2–3 Zeichen Kürzel | frei vergeben |
| **Schrank** (`S`) | Schrank, Regal, Werkzeugwand, Tisch oder Werkbank | pro Bereich ab 1 |
| **Ebene** (`E`) | Fach, Schublade oder Tischplatte | **von oben nach unten** |
| **Position** (`P`) | Platz in der Ebene (Schattenbrett-Feld, Fachteiler) | **von links nach rechts**, bei Frontansicht |

- Werkzeugwand: Ebene = Reihe, Position = Spalte.
- **Die 0-Regel:** `0` heisst auf jeder Stufe «nicht unterteilt oder noch nicht
  festgelegt». Echte Schränke, Ebenen und Positionen starten bei 1.
  - `S0` = liegt im Bereich, aber in keinem Möbel (Kisten, Boden). Pro Bereich fest vorhanden.
  - `E0` = im Möbel, Ebene unbestimmt (Regal ohne Fachböden, Tischplatte, beim Umzug «Ebene noch offen»). Entsteht automatisch mit jedem Möbel.
  - `P0` = auf der Ebene, ohne feste Position (keine Fachteiler). Entsteht automatisch mit jeder Ebene.
  - Beispiel: `HO-S3-E0-P0` = irgendwo auf Werkbank 3 im Holzbereich.
- **Anzeige gekürzt:** Auf Etiketten und in Listen entfallen abschliessende Nullen
  (`HO-S1-E2` statt `HO-S1-E2-P0`). Suche und QR-Ziele akzeptieren beide Schreibweisen.
- Ein Werkzeug mit **gar keinem Bereich** («noch nirgends erfasst») ist weiterhin möglich;
  das ist etwas anderes als `S0-E0-P0`.
- Wird ein Möbel nachträglich unterteilt, bleiben die Dinge auf `E0` und erscheinen als
  «noch nicht zugeordnet»; man zieht sie auf die neuen Ebenen.
- Der Code wird **immer aus der Struktur berechnet**, nie von Hand getippt.
- **Bereich = Fachgebiet, nicht Raumzone.** Ein Elektronikschrank bleibt `EL`, auch wenn
  er im neuen Raum woanders steht. Der Raumbezug lebt nur im Plan.
- **Wechselt ein Schrank den Bereich**, ändert sich sein Code. Das Modul markiert ihn als
  «Etikett veraltet» und führt ihn in der Liste «Etiketten neu drucken».
- Die Einträge «Hilti Schrank 1/2» sind in Wahrheit Schränke und werden von Hand
  einem Bereich zugeordnet (siehe Migration).

## 4. Datenmodell

Alle neuen Tabellen mit Präfix `inv_`. Anlage über `Base.metadata.create_all()`, neue
Spalten an bestehenden Tabellen über `_add_column_if_missing` (Migration **v1.51**,
nächste freie Nummer nach v1.50; nur additiv).

### 4.1 Erweiterung `machine_locations` (= Bereich)

| Spalte | Typ | Zweck |
|---|---|---|
| `code` | `VARCHAR(4)` unique, nullable | Kürzel (`EL`, `HO`, `LA` …) |
| `color` | `VARCHAR(9)` nullable | Farbe für Etiketten und Plan |
| `plan_x`, `plan_y`, `plan_w`, `plan_h` | `FLOAT` nullable | Rechteck des Bereichs im Plan (cm) |

Bestehende Zeilen bleiben gültig; `code` ist zunächst leer.

### 4.2 `machines`: Zuordnung zum Bereich

**Befund:** `Machine.location` ist ein freier Text (`VARCHAR(200)`), **kein Fremdschlüssel**.
Die Formulare füllen ihn zwar aus der Standortliste, gespeichert wird aber der Name.
Deshalb:

| Neu in `machines` | Typ | Zweck |
|---|---|---|
| `area_id` | FK → `machine_locations.id`, `SET NULL`, nullable | massgeblicher Bereich |

- Beim Start wird `area_id` einmalig aus `location` befüllt (Namensvergleich,
  idempotent, nur wo `area_id` leer ist). Nicht zuordenbare Texte bleiben unberührt und
  erscheinen in einer Liste «Maschinen ohne Bereich».
- **Bereichswechsel** (Maschine zieht um): `area_id` ändern; der Text `location`
  wird **mitgeschrieben** (Write-Through), damit CSV-Export, Display, Inventarliste und
  alle bestehenden Ansichten weiter stimmen. Der Wechsel wird im Aktivitätslog
  protokolliert (`machine_area_changed`, alter und neuer Bereich in `meta`).
- Die Platzierung im Plan liegt **nicht** in `machines`, sondern in `inv_placements`
  (4.7), damit der Maschinenbestand schmal bleibt.

### 4.3 `inv_furniture` (Schrank, Regal, Wand, Tisch)

| Spalte | Typ | Hinweis |
|---|---|---|
| `id` | PK | |
| `area_id` | FK → `machine_locations`, `RESTRICT` | |
| `number` | `INT` | eindeutig pro Bereich (`area_id`, `number`); **0 = «kein Möbel»**, pro Bereich genau eine Zeile `S0`, entsteht automatisch, nicht löschbar |
| `kind` | ENUM `schrank`/`regal`/`wand`/`tisch` | nur Anzeige und Symbol (`tisch` gilt auch für Werkbänke) |
| `name` | `VARCHAR(100)` nullable | Alltagsname («Hilti Schrank 1») |
| `plan_x`, `plan_y`, `plan_w`, `plan_h`, `plan_rot` | `FLOAT` nullable | Platz im Plan (cm, Grad) |
| `label_outdated` | `BOOL` | Etikett muss neu gedruckt werden |
| `note` | `TEXT` nullable | |

### 4.4 `inv_levels` (Ebene)

`id`, `furniture_id` (FK, `CASCADE`), `number` (eindeutig pro Schrank), `label` (optional).
`number = 0` (`E0`) wird mit jedem Möbel automatisch angelegt und ist nicht löschbar.

### 4.5 `inv_positions` (Position)

`id`, `level_id` (FK, `CASCADE`), `number` (eindeutig pro Ebene), `label` (optional).
`number = 0` (`P0`) wird mit jeder Ebene automatisch angelegt und ist nicht löschbar.

### 4.6 `inv_items` (Werkzeug und Kleingerät)

| Spalte | Typ | Hinweis |
|---|---|---|
| `id` | PK | |
| `name` | `VARCHAR(150)` | |
| `synonyms` | `TEXT` | kommagetrennt, **zentral für die Suche** («Bohrschrauber, Schrauber») |
| `description` | `TEXT` nullable | |
| `quantity` | `INT` default 1 | |
| `position_id` | FK → `inv_positions`, `SET NULL`, nullable | Heimatplatz; Ebene, Möbel und Bereich ergeben sich daraus. `NULL` = noch nirgends erfasst |
| `status` | ENUM `aktiv`/`defekt`/`ausgemustert` | |
| `photo` | `VARCHAR(255)` nullable | siehe Offene Punkte |
| `created_at`, `updated_at` | | |

- **Genau ein Heimatplatz** pro Eintrag. Mehrere Exemplare: `quantity` oder eigene Zeile.
- Ohne Platz (`position_id = NULL`) ist erlaubt; solche Einträge stehen in einer
  eigenen Liste. Mit den Nullplätzen (`S0`, `E0`, `P0`) lässt sich beim Umzug schrittweise
  verfeinern; «Ebene noch offen» ist ein Filter.
- Kaufdatum, Neuwert und Eigentümer sind **bewusst nicht** enthalten; sie bleiben bei
  den Maschinen. Bei Bedarf später nullable ergänzen.

### 4.7 `inv_placements` (Maschinen im Plan)

`machine_id` (PK/FK → `machines`, `CASCADE`), `furniture_id` (FK → `inv_furniture`,
`SET NULL`, nullable, «steht auf»), `plan_x`, `plan_y`, `plan_w`, `plan_h`, `plan_rot`.
Eine Zeile pro platzierte Maschine. Der Bereich kommt aus `machines.area_id`.
Ist `furniture_id` gesetzt, zeigt die Suche «3D-Druck › Tisch 1» und der Plan die Maschine
auf diesem Möbel. Die Maschine bekommt dadurch keinen Code und keine Ebene.

### 4.8 `inv_plan` (Raum)

Eine Zeile: `width_cm`, `height_cm`, `name`. Zieht der Makerspace um, wird der Plan
neu gezeichnet; Codes und Zuordnungen bleiben gültig, nur Koordinaten ändern sich.

### 4.9 Einstellung

`system_settings.inventory_enabled` (Bool, Default `false`). Ist es aus, sind Menüpunkt,
Gästesuche und alle `/api/inventory/*`-Endpoints ohne Funktion (404 bzw. versteckt).
Dafür die **drei Stellen** aus «Settings» beachten: `models.py`, `routers/settings.py`
(`SettingsOut`, `SettingsUpdate`, PATCH-Handler) und `migrate.py`; zusätzlich in
`read_settings_public()`, damit die Gast-App den Schalter kennt.

## 5. Rollen

| Aktion | Gast | Manager | Power-Manager | Admin |
|---|:---:|:---:|:---:|:---:|
| Suchen, Orte und Plan ansehen | ✓ (nur Lesen) | ✓ | ✓ | ✓ |
| Werkzeug anlegen, bearbeiten, umlagern | ✗ | ✓ | ✓ | ✓ |
| Bereiche, Schränke, Ebenen, Positionen anlegen/ändern | ✗ | ✗ | ✓ | ✓ |
| Plan zeichnen, Maschinen platzieren, Bereich wechseln | ✗ | ✗ | ✓ | ✓ |
| Modul ein- und ausschalten | ✗ | ✗ | ✗ | ✓ |

Umsetzung mit den vorhandenen Abhängigkeiten `get_current_user`, `require_power_manager`
und `require_admin`. Der Gast-Lesezugriff nutzt das Gast-Token-System aus `guest_auth.py`.

## 6. Schnittstellen (Entwurf)

Neuer Router `routers/inventory.py`, Präfix `/api/inventory`. Alle schreibenden Aktionen
mit `log_svc.log()` und `user_id`.

```
GET    /inventory/tree                 Bereich → Schrank → Ebene → Position, mit Codes
GET    /inventory/search?q=            Maschinen + Werkzeug, mit Code, Ort und Plan-Ziel
GET    /inventory/code/{code}          Inhalt eines Schranks/einer Ebene (Ziel der QR-Codes)
GET    /inventory/plan                 Plan inkl. Bereiche, Schränke, Maschinen
POST/PATCH/DELETE  /inventory/furniture, /levels, /positions
POST   /inventory/furniture/{id}/levels   Ebenen und Positionen in einem Schritt anlegen
POST/PATCH/DELETE  /inventory/items
POST   /inventory/items/{id}/move      umlagern
PUT    /inventory/placements/{machine_id}
PATCH  /machines/{id}                  erhält area_id (bestehender Endpoint)
GET    /inventory/labels?ids=…         Etiketten als druckbares HTML/PDF
GET    /guest/inventory/search?q=      Lesezugriff für angemeldete Gäste
```

**Suche:** Treffer in Name, Synonymen, Beschreibung, Code und Bereichsname, ohne Beachtung
von Gross-/Kleinschreibung. Ergebnis enthält `type` (`tool`/`machine`), `code` bzw.
`area`, `path` (Klartext, z. B. «Elektronik › Schrank 2 › Ebene 3 › Platz 4») und
`plan_target`. Maschinen werden nicht auf Basis von `plug_id` gefiltert; im Gegensatz zu
Display und Gast-Dashboard zählt hier der Inventargedanke.

## 7. Oberfläche

- **Admin-Oberfläche als nachladbares Modul** (`frontend/modules/inventory.js`): Eine eigene Seite
  wirkte wie ein Fremdkörper (keine Seitenleiste, eigener Kopf, eigener Login-Zustand). Darum ist das
  Inventar eine normale Seite des LabManagers, deren Code beim ersten Öffnen nachgeladen wird:
  - `labmanager.html` enthält nur den Lader `LabModules`, den Menüpunkt (`data-module="inventory"`,
    sichtbar nur bei `inventory_enabled`) und den leeren Container `page-inventory`.
  - Das Modul nutzt die Helfer des LabManagers (`GET/POST/PATCH/DELETE`, `showToast`, `openModal`,
    `escHtml`, `currentUser`, `_isPowerPlus()`), also gleiches Aussehen, gleiche Anmeldung, gleiches
    Hell/Dunkel. Alle Namen liegen im Namensraum `Inv`, alle CSS-Klassen tragen das Präfix `inv-`.
  - Cache: Das Skript wird mit `?v=<Build-Nummer>` geladen.
  - **Etikettendruck:** Gedruckt wird in einem unsichtbaren `iframe` mit eigenen Seitenregeln
    (`@page`); das Drucken anderer LabManager-Seiten bleibt unberührt.
- **`frontend/inventar.html`** ist nur noch ein Einsprung: QR-Codes auf Schränken zeigen auf
  `/inventar.html?code=EL-S1`, das nach `/labmanager.html#inventory/EL-S1` weiterleitet (Inhalt des
  Schranks gefiltert). In Etappe 3 wird daraus die schlanke Gäste-Seite ohne Sidebar.
- Bereiche der Seite:
  1. **Struktur:** Baumansicht, Schrank mit Ebenen und Positionen in einem Dialog anlegen.
  2. **Werkzeug:** Tabelle mit Suche und Filter, Anlegen/Bearbeiten, Umlagern, «Ohne Platz».
  3. **Maschinen:** Bereich zuordnen und wechseln, Liste «ohne Bereich».
  4. **Etiketten und Listen:** Druckansicht pro Bereich/Schrank, QR-Codes, «Etikett veraltet».
  5. **Plan** (Etappe 4): Zeichnen, Verschieben, Suchtreffer hervorheben.
- **Gäste:** Suchfeld in `index.html` («Wo ist …?»). QR-Codes auf Schränken führen auf
  den Inhalt dieses Schranks (`/inventar.html?code=EL-S2` bzw. Gast-Variante).
- Sprache: Du-Form, deutsche Begriffe wie bisher («Aushänge», «Push-Nachrichten»).

## 7a. Weitere Auslagerungs-Kandidaten im LabManager (nicht Teil dieses Moduls)

`labmanager.html` hat über 8000 Zeilen (5500 Skript, 307 globale Funktionen). Mit dem Lader lassen sich
selten genutzte oder abgeschlossene Bereiche auslagern. Vermessung (Zeilen, grob):

| Bereich | Umfang | Kopplung | Priorität |
|---|---|---|---|
| Hilfe + Info (fast nur statisches HTML) | ~1500 | keine | 1 — grösster Gewinn, kleinstes Risiko |
| Plug-Pool + Geräte-/NFC-Discovery | ~920 | gering | 2 |
| Einstellungen (+ Backup, Update, Tailscale, MCP) | ~1200 | mittel | 3 (nur Admins) |
| Berechtigungen | ~420 | mittel | bei Bedarf |
| Automationen (+ Bedingungen-Editor) | ~250 | gering | bei Bedarf |
| Akkus | ~175 | gering | später evtl. ins Inventar-Modul (Lagerort) |
| Dashboard, Gäste, Maschinen | — | hoch | im Kern lassen |

Regel: nur auslagern, wenn man dort ohnehin etwas ändert; je Bereich ein eigener Branch. Bei «alten»
Bereichen genügt es, den Code unverändert zu verschieben (Funktionen bleiben global, `onclick`
funktioniert weiter); zu prüfen sind Funktionen, die der Kern vor dem Nachladen aufruft (z.B.
`loadPlugs()` beim Start).

## 7b. Etiketten und Vorlagen

Standard sind **vorgeschnittene A4-Bögen** (Avery Zweckform Typenschild-Etiketten L6009-20,
45,7 × 21,2 mm, 4 × 12 = 48 pro Bogen; dasselbe Raster haben L4736 und L6040).

- **Vorlagen** sind in `modules/inventory.js` (`TEMPLATES`) als Daten beschrieben (Etikettgrösse, Spalten,
  Zeilen, Rand links/oben, Abstand). Weitere Bögen lassen sich durch einen Eintrag ergänzen. Daneben
  gibt es Einzeletiketten zum Ausschneiden (60×30, 90×50, 100×60 mm).
- **Raster L6009:** links 9,85 mm, oben 21,3 mm, Spaltenabstand 48,2 mm, Zeilenabstand 21,2 mm
  (Quelle: Datenblatt eines kompatiblen Herstellers, mr-label.com MR109; symmetrisch zentriert auf A4).
  **Nicht an einem Originalbogen verifiziert** — darum gibt es den **Testbogen** (Raster mit
  Nummern 1–48 auf normales Papier drucken, gegen das Licht über den Bogen halten) und einen
  einstellbaren **Versatz X/Y** (wird im Browser gemerkt).
- **Startposition:** «Beginnen bei Nr.» erlaubt, angebrochene Bögen weiterzuverwenden.
- **Inhalt je Etikett:** QR-Code (führt zum Inhalt des Möbels/der Ebene), Code in Grossschrift
  (Schriftgrösse passt sich der Codelänge an), Name; Farbbalken des Bereichs.
- **Druckdialog:** Papier A4, Skalierung 100 % («Tatsächliche Grösse»), Kopf-/Fusszeilen aus, Ränder keine.
  L6009 ist für Laserdrucker gedacht.

## 8. Backup

Neue Top-Level-Sektion `inventory` in `_build_export_data` und `_do_import`:
`areas` (Erweiterungsfelder), `furniture`, `levels`, `positions`, `items`,
`placements`, `plan`. Die Kompatibilitätsregeln gelten: Lesen nur mit
`payload.get("inventory", {})` und `.get("feld", default)`.

Beim Restore die Reihenfolge einhalten (Bereiche → Maschinen → Möbel → Ebenen →
Positionen → Werkzeug → Platzierungen) und Fremdschlüssel über **natürliche Schlüssel**
auflösen (Bereichs-Code, `furniture`-Nummer, Ebenen-Nummer), nicht über DB-IDs, wie schon
bei den Plugs und Eigentümern. Werkzeug wird beim Import über den **natürlichen Schlüssel**
(Name + Ebenen-Code) dedupliziert, analog zu den Akkus (Merkmals-Schlüssel). Fotos sind
nicht Teil des JSON-Backups (siehe Offene Punkte).

## 9. Migration

Idempotent, rein additiv, bei jedem Start:

1. Spalten an `machine_locations` und `machines` ergänzen, neue Tabellen anlegen.
2. `machines.area_id` aus `machines.location` befüllen (nur Treffer mit gleichem Namen).
3. Kürzel für Bereiche **nicht automatisch** vergeben; sie werden einmal im UI gesetzt.
4. Standorte «Hilti Schrank 1/2» bleiben bis zum Umzug bestehen; ein Power-Manager legt
   die tatsächlichen Schränke an und weist die Maschinen dem richtigen Bereich zu.

## 10. Etappen

| Etappe | Inhalt | Ergebnis |
|---|---|---|
| **0** | Dieses Konzept abstimmen | Freigabe durch Martin |
| **1** ✅ | Migration, Modelle, Router (Struktur, Werkzeug, Suche), `inventar.html` (Struktur, Werkzeug, Import, Etiketten) auf der **Dev-Instanz** | Nutzbar fürs Einpacken und Inventarisieren beim Umzug |
| **2** | `machines.area_id`, Backfill, Bereichswechsel, Anzeige in der Suche, Backup-Sektion und Restore-Test | Maschinen und Werkzeug in einer Suche |
| **3** | Gästesuche in `index.html`, QR-Ziele für Schränke | Neue Gäste finden Dinge selbst |
| **4** | Bauplan (Zeichnen, Verschieben, Suchtreffer-Markierung, Maschinen platzieren) | nach dem Umzug, sobald das Layout feststeht |
| **5** | Optional: Fotos, Foto-Inventur per KI, Lesezugriff über den MCP-Server | |

### Rollout und Betrieb

- **Entwicklung und Test** auf der Dev-Instanz `spacecaptain01.pe.lan`
  (Pfad `/home/martin/spacecaptain`). Per SSH nur mit `-i …\claudecode -o IdentitiesOnly=yes`.
- **Nie per SCP deployen:** committen, nach `origin/main` pushen, dann «Update starten» im
  UI (Update-Watcher). Der Dev-Deploy (`git pull` + Rebuild) bleibt bei Martin.
- **Produktion** (`mscaptain01`, `/opt/spacecaptain`, via Tailscale) erst nach erfolgreichem
  Dev-Test und mit ausdrücklicher Freigabe von Martin, per «Update starten».
- `inventar.html` ist eine statische Datei im gemounteten `frontend/`-Verzeichnis; an
  `nginx/proxy.conf` ändert sich nichts.
- `APP_VERSION` wird von Martin manuell hochgesetzt (aktuell 1.42), nicht automatisch.

### MCP (Etappe 5)

Der MCP-Server bekommt nur **lesende** Tools (`list_inventory`, `search_inventory`,
`get_inventory_location`), passend zur bestehenden Linie «keine Anlage- und
Löschfunktionen im MCP». Neue Tools in `mcp_server/main.py` mit Endpunkt in `mcp_api.py`
(`Depends(require_mcp)`).

Ausgerollt wird auf Produktion erst nach Test auf der Dev-Instanz und mit ausdrücklicher
Freigabe von Martin.

## 11. Tests (Mindestumfang)

- Codeberechnung: Zählregeln, Position optional, Bereichswechsel setzt `label_outdated`.
- Eindeutigkeit: `(area_id, number)`, `(furniture_id, number)`, `(level_id, number)`.
- Suche: Treffer über Synonyme, Code, Bereichsname; Maschine und Werkzeug in einer Liste.
- Rechte: Gast liest nur, Manager nur Werkzeug, Power-Manager Struktur, Modul-Schalter nur Admin.
- Migration: zweimal starten ändert nichts; Backfill von `area_id`.
- Backup: Export/Import mit und ohne Sektion `inventory` (altes Backup darf nicht brechen).
- Bereichswechsel einer Maschine aktualisiert `area_id` und `location` und schreibt das Log.

## 11a. Stand Etappe 1: Abweichungen und Grenzen

- **Kein DB-Fremdschlüssel** von `inv_furniture.area_id` auf `machine_locations.id`: Der Typ dieser
  Spalte ist je nach Installation signed (vom ORM) oder unsigned (`init.sql`); ein FK würde beim
  Start mit `errno 150` scheitern (Vorfall `b24a3e9`). Die Integrität sichert die Anwendung:
  Bereiche mit Möbeln oder Werkzeug lassen sich nicht löschen (409).
- **Nullplätze entstehen auch nachträglich:** Standorte, die per CSV-Import oder Backup-Restore
  angelegt werden, bekommen `S0/E0/P0` beim nächsten Aufruf des Moduls.
- **Noch nicht im Backup** (Etappe 2): Kürzel, Farben, Möbel und Werkzeug sind in der
  JSON-Sicherung noch nicht enthalten. Bis dahin gilt die DB-Sicherung der Maschine.
- **Nummern bleiben stabil:** Wird eine Ebene oder Position gelöscht, rücken die übrigen nicht
  nach (aufgedruckte Etiketten würden sonst falsch).
- **Maschinen** sind in Suche und Plan erst ab Etappe 2 enthalten.
- Der Menüpunkt «Inventar» erscheint nur, wenn das Modul in den Einstellungen (Admin) eingeschaltet ist.

## 12. Offene Punkte

1. **Fotos:** Wo liegen die Bilder (eigenes Volume `inventory_media`)? JSON-Backup enthält
   sie nicht; es braucht ein separates Sicherungs- und Restore-Verfahren oder den
   Verzicht in Etappe 1.
2. ~~Positionen ohne Fachteiler~~ → entschieden: 0-Regel (`P0`), siehe Abschnitt 3.
3. ~~Token-Teilung~~ → erledigt: Das Modul läuft im LabManager und teilt dessen Anmeldung.
4. ~~Etiketten: Format und Grösse~~ → entschieden: vorgeschnittene A4-Bögen (Avery L6009-20), siehe 7b.
   Offen: Raster am echten Bogen bestätigen.
5. **Verbrauchsmaterial und Akkus:** Die vorhandene Akku-Verwaltung (`batteries`, eigene
   Seite unter AUSSTATTUNG) bleibt getrennt. Sollen Akkus später auch einen Lagerort
   bekommen (`position_id` an `batteries`)? Da Akkus als loser Pool gelten,
   wäre das eine nullable Ergänzung ohne Umbau.
6. **Mehrfachstandorte** (Werkzeug in mehreren Schränken): bewusst nicht vorgesehen.
