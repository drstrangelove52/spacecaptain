# Konzept: Modul «Inventar & Standorte»

Status: **Etappen 1 und 2 umgesetzt** (2026-10-19, Branch `feature/inventar-modul`; Dev-Test läuft). Etappen 3–5 offen. Backend: `models_inventory.py`, `services/inventory.py`,
`routers/inventory.py`; Oberfläche: `frontend/modules/inventory.js` (Modul im LabManager); Tests: `backend/tests` (`cd backend && pytest`).

Planungsebene im Second Brain: `03 Bereiche/SpaceCaptain/Inventar-Modul.md`.

## 1. Ziel

Zwei Probleme im Makerspace lösen:

1. **Neue Gäste finden Werkzeug und Maschinen nicht.**
2. **Werkzeug landet im falschen Schrank.**

Dazu bekommt jedes Ding einen **eindeutigen, aufgedruckten Standort-Code**, es gibt eine
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
| 4 | Maschinen tragen **keinen aufgedruckten Standort-Code**, sondern Bereich + Platz auf dem Plan. Sie können den Bereich wechseln |
| 5 | **Die 0 bedeutet «nicht unterteilt oder noch nicht festgelegt»** auf jeder Stufe (`M00`, `E00`, `P00`). Jeder Code hat dieselbe Form, es gibt keine `NULL`-Plätze |
| 6 | **Tische und Werkbänke** sind normale Möbel (`kind = tisch`), Maschinen können optional «auf» einem Möbel stehen |

## 3. Begriffe und Code-Schema

```
<Bereich>-M<Möbel>-E<Ebene>-P<Position>      Beispiel: ELE-M02-E03-P04
```

| Stufe | Bedeutung | Zählregel |
|---|---|---|
| **Bereich** | Fachgebiet (Holz, Elektronik, Laser …); **genau 3 Zeichen** Kürzel (`ELE`, `HOL`, `LAS`) | frei vergeben, eindeutig |
| **Möbel** (`M`) | Schrank, Regal, Werkzeugwand, Tisch oder Werkbank | pro Bereich ab 01 |
| **Ebene** (`E`) | Fach, Schublade oder Tischplatte | **von oben nach unten** |
| **Position** (`P`) | Platz in der Ebene (Schattenbrett-Feld, Fachteiler) | **von links nach rechts**, bei Frontansicht |

- **Alle Nummern sind zweistellig mit führender Null** (`M01`, `E02`, `P03`). Beim Eingeben genügt `M1`, die Anzeige
  ist immer zweistellig. (Frühere Fassung: `EL-S1-E2-P3` — der Buchstabe `S` für «Schrank» passte nicht für Tische
  und Wandregale, das Kürzel hatte 2–4 Zeichen.)
- **Kürzel mit 3 Zeichen:** Zwei Zeichen kollidieren schnell (Holz und Hobby), drei bleiben gut lesbar. Der Vorschlag
  kommt aus dem Namen: «Elektronik» → `ELE`, «Precious Plastic» → `PPL`, «3D-Druck» → `3DR`. Kürzel aus früheren Fassungen
  (2 oder 4 Zeichen) werden beim nächsten Aufruf des Moduls automatisch auf 3 Zeichen umgestellt; die Etiketten der
  betroffenen Möbel gelten dann als «neu/veraltet».
- Werkzeugwand: Ebene = Reihe, Position = Spalte.
- **Die 0-Regel:** `00` heisst auf jeder Stufe «nicht unterteilt oder noch nicht
  festgelegt». Echte Möbel, Ebenen und Positionen starten bei 01.
  - `M00` = liegt im Bereich, aber in keinem Möbel (Kisten, Boden). Pro Bereich fest vorhanden.
  - `E00` = im Möbel, Ebene unbestimmt (Regal ohne Fachböden, Tischplatte, beim Umzug «Ebene noch offen»). Entsteht automatisch mit jedem Möbel.
  - `P00` = auf der Ebene, ohne feste Position (keine Fachteiler). Entsteht automatisch mit jeder Ebene.
  - Beispiel: `HOL-M03-E00-P00` = irgendwo auf Werkbank 3 im Holzbereich.
- **Anzeige gekürzt:** Auf Etiketten und in Listen entfallen abschliessende Nullen
  (`HOL-M01-E02` statt `HOL-M01-E02-P00`). Suche und QR-Ziele akzeptieren beide Schreibweisen.
- Ein Werkzeug mit **gar keinem Bereich** («noch nirgends erfasst») ist weiterhin möglich;
  das ist etwas anderes als `M00-E00-P00`.
- Wird ein Möbel nachträglich unterteilt, bleiben die Dinge auf `E00` und erscheinen als
  «noch nicht zugeordnet»; man zieht sie auf die neuen Ebenen.
- Der Code wird **immer aus der Struktur berechnet**, nie von Hand getippt.
- **Bereich = Fachgebiet, nicht Raumzone.** Ein Elektronikschrank bleibt `ELE`, auch wenn
  er im neuen Raum woanders steht. Der Raumbezug lebt nur im Plan.
- **Wechselt ein Möbel den Bereich**, ändert sich sein Code. Das Modul markiert es als
  «Etikett neu/veraltet» und führt es in der Liste der neu zu druckenden Etiketten.
- Die Einträge «Hilti Schrank 1/2» sind in Wahrheit Möbel und werden von Hand
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
| `number` | `INT` | eindeutig pro Bereich (`area_id`, `number`); **0 = «kein Möbel»**, pro Bereich genau eine Zeile `M00`, entsteht automatisch, nicht löschbar |
| `kind` | ENUM `schrank`/`regal`/`wand`/`tisch` | nur Anzeige und Symbol (`tisch` gilt auch für Werkbänke) |
| `name` | `VARCHAR(100)` nullable | Alltagsname («Hilti Schrank 1») |
| `plan_x`, `plan_y`, `plan_w`, `plan_h`, `plan_rot` | `FLOAT` nullable | Platz im Plan (cm, Grad) |
| `label_outdated` | `BOOL` | Etikett muss neu gedruckt werden |
| `note` | `TEXT` nullable | |

### 4.4 `inv_levels` (Ebene)

`id`, `furniture_id` (FK, `CASCADE`), `number` (eindeutig pro Schrank), `label` (optional).
`number = 0` (`E00`) wird mit jedem Möbel automatisch angelegt und ist nicht löschbar.

### 4.5 `inv_positions` (Position)

`id`, `level_id` (FK, `CASCADE`), `number` (eindeutig pro Ebene), `label` (optional).
`number = 0` (`P00`) wird mit jeder Ebene automatisch angelegt und ist nicht löschbar.

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
  eigenen Liste. Mit den Nullplätzen (`M00`, `E00`, `P00`) lässt sich beim Umzug schrittweise
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
GET    /inventory/tree                 Bereich → Möbel → Ebene → Position, mit Codes
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
`area`, `path` (Klartext, z. B. «Elektronik › Schrank 2 › Ebene 3 › Platz 4» (Möbelart und -nummer oder eigener Name)) und
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
  `/inventar.html?code=ELE-M01`, das nach `/labmanager.html#inventory/ELE-M01` weiterleitet (Inhalt des
  Schranks gefiltert). In Etappe 3 wird daraus die schlanke Gäste-Seite ohne Sidebar.
- Bereiche der Seite:
  1. **Struktur:** Baumansicht, Schrank mit Ebenen und Positionen in einem Dialog anlegen.
  2. **Werkzeug:** Tabelle mit Suche und Filter, Anlegen/Bearbeiten, Umlagern, «Ohne Platz».
  3. **Maschinen:** Bereich zuordnen und wechseln, Liste «ohne Bereich».
  4. **Etiketten und Listen:** Druckansicht pro Bereich/Schrank, QR-Codes, «Etikett veraltet».
  5. **Plan** (Etappe 4): Zeichnen, Verschieben, Suchtreffer hervorheben.
- **Gäste:** Suchfeld in `index.html` («Wo ist …?»). QR-Codes auf Schränken führen auf
  den Inhalt dieses Schranks (`/inventar.html?code=ELE-M02` bzw. Gast-Variante).
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
| Akkus | ~175 | gering | später evtl. ins Inventar-Modul (Standort) |
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
- **Layout des Reiters:** zweispaltig. Links die **Auswahl** (in voller Höhe scrollbar, Möbel/Ebenen/Positionen
  bzw. Werkzeug), rechts **Vorlage, Startposition, Versatz, Druckknopf und die Bogenvorschau**, die in der
  Spalte mitscrollt (sticky) und deren Massstab sich der Spaltenbreite anpasst. Unter 1180 px Breite stapeln sich
  die Spalten (Auswahl oben).
- **Auswahl und Anzahl:** Gedruckt wird nur, was in der Liste angehakt ist (Möbel-, Ebenen- und
  Positions-Etiketten einzeln), **jedes in der gewünschten Anzahl** (Feld «Anzahl»; eintippen wählt die Zeile,
  0 wählt ab). Der Zähler nennt Etiketten und Stückzahl, der Druckknopf die Gesamtzahl («15 Etiketten drucken»),
  der Tooltip die Bogenzahl. Schnellwahl: Alle, Keine, Neue/veraltete, Nur Möbel, Nur Ebenen, Nur Positionen;
  je Möbel «Ebenen ✓/✗». Vorschau und Druck zeigen genau die Auswahl.
- **Inhalt auf dem Etikett:** Die Liste zeigt je Ebene und Position, **was dort liegt** («Lineal 30 cm ×12, Zollstock ×5»;
  leere Plätze sind als «leer» markiert). Ebenen- und Positions-Etiketten drucken **nur Code und Inhalt** («WER-M01-E02 · Lineal 30 cm, Zollstock»), **ohne Mengen** (die Menge steht nur in der Auswahlliste);
  der Standardname «Ebene 2»/«Platz 1» entfällt. Ein selbst vergebener Name («Obere Schublade») erscheint weiterhin, und bei
  einer leeren Ebene oder Position dient der Standardname als Rückfall. Es werden so viele
  Werkzeuge ausgeschrieben, wie bei lesbarer Schrift (mindestens 2,8 mm) passen, der Rest als «… +n».
  Die Daten liefert `GET /api/inventory/labels` (je Möbel, Ebene und Position: `items` (max. 8/12) und `item_count`). **Nachdruck:** im Strukturbaum öffnet 🏷️ beim Möbel oder der Ebene
  den Reiter mit genau diesem Etikett vorgewählt.
- **«Neu/veraltet»:** Ein neu angelegtes Möbel gilt als «Etikett noch nicht gedruckt»; ebenso, wenn sich
  sein Code ändert (Kürzel oder Bereich). Nach dem Druck fragt das Modul, ob die Etiketten als gedruckt
  markiert werden sollen. Zurückgesetzt wird das Kennzeichen nur, wenn das Möbel-Etikett **und alle**
  Ebenen-Etiketten dieses Möbels gedruckt wurden (ändert sich ein Code, ändern sich alle). Ein später
  hinzugefügte Ebene setzt das Kennzeichen nicht; ihr Etikett wählt man von Hand.
- **Inhalt je Etikett (Möbel/Ebene):** QR-Code (führt zum Inhalt des Möbels/der Ebene), Code in
  Grossschrift (Schriftgrösse passt sich der Codelänge an), Name; Farbbalken des Bereichs.
- **Werkzeug-Etiketten** (Etikettenart «Werkzeug»): **ein Etikett pro Stück**, z.B. «Lineal 30 cm», Menge 12 →
  12 Etiketten. Es wird nur **ein** Eintrag mit Menge geführt, nicht jedes Lineal einzeln. Kopien = Menge
  (je Werkzeug anpassbar, max. 200). Auf dem Etikett stehen der **Name** (die Schrift wird so berechnet, dass
  auch lange Namen vollständig passen) und der **Heimatort** («→ HOL-M01-E02»). Sie haben kein
  «gedruckt»-Kennzeichen; die Auswahl bestimmt, was gedruckt wird.
- **QR-Ziele:**
  | Etikett | Ziel des QR-Codes | Bleibt gültig bei … |
  |---|---|---|
  | Möbel / Ebene | `/inventar.html?code=ELE-M01` → Inhalt dieses Möbels | Änderung des Codes nicht (Etikett wird «veraltet» und neu gedruckt) |
  | Werkzeug | `/inventar.html?item=<ID>` → «**gehört nach** HOL-M01-E02 · Holz › Regal 1 › Ebene 2» | Umlagern (der Link zeigt immer den aktuellen Ort) |

  Beide führen auf die schlanke Gäste-Seite `/inventar.html` ohne Anmeldung (nur Lesen, seit Etappe 3, siehe 11d). Das Werkzeug-Etikett beantwortet damit auch
  «wohin gehört das?» für Werkzeug, das im falschen Schrank gelandet ist.
- **Druckdialog:** Papier A4, Skalierung 100 % («Tatsächliche Grösse»), Kopf-/Fusszeilen aus, Ränder keine.
  L6009 ist für Laserdrucker gedacht.

## 8. Backup

Umgesetzt in `services/inventory_backup.py` (Export und Import), eingehängt an zwei Stellen in `routers/backup.py`
(`_build_export_data`: Sektion `inventory`; `_do_import`: vor dem Aktivitätslog). Die Kompatibilitätsregeln gelten:
fehlt die Sektion in einem älteren Backup, wird sie übersprungen; Felder werden mit `.get()` gelesen.

Inhalt der Sektion `inventory`:

| Teil | Inhalt | Verweis auf andere Daten |
|---|---|---|
| `areas` | Kürzel, Farbe, Plan-Rechteck je Bereich (die Bereiche selbst stehen in `machine_locations`) | Bereichsname |
| `furniture` | Möbel (ohne das automatische M00) mit `levels` und `positions` (ohne die automatischen E00/P00), Art, Name, Notiz, «neu/veraltet», Plan-Rechteck | Bereichsname + Möbelnummer |
| `items` | Werkzeug mit Menge, Synonymen, Status und `place` (Bereich, Möbel-, Ebenen-, Positionsnummer; `null` = ohne Platz) | natürliche Schlüssel |
| `placements` | Maschine «steht auf» Möbel, Plan-Koordinaten | Maschinenname, Bereich + Möbelnummer |

Es gibt **keine DB-IDs** im Export. Der Import läuft in der Transaktion des Aufrufers: Bereichs-Kürzel und -Farben (ein
Kürzel wird nur gesetzt, wenn es gültig und frei ist), Nullplätze und Kürzel-Umstellung (`ensure_structure`), Möbel/Ebenen/
Positionen, Nullplätze der neuen Möbel, Werkzeug, Platzierungen. **Ohne «Überschreiben»** bleibt Vorhandenes unberührt und
nur Fehlendes wird ergänzt (ein zweiter Import legt nichts doppelt an); mit «Überschreiben» werden Felder aktualisiert.
Werkzeug wird über (Name, Platz) dedupliziert. Fotos sind nicht Teil des JSON-Backups (siehe Offene Punkte).
Statistik im Ergebnis: `inventory_areas`, `inventory_furniture`, `inventory_levels`, `inventory_items`, `inventory_placements`.

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
| **2** ✅ | `machines.area_id`, Backfill, Bereichswechsel, «steht auf», Anzeige in der Suche, Backup-Sektion und Restore-Test | Maschinen und Werkzeug in einer Suche |
| **3** ✅ | Gästesuche («Wo ist …?»), QR-Ziele für Möbel, Ebenen und Werkzeug, ohne Anmeldung | Neue Gäste finden Dinge selbst |
| **4** ✅ | Bauplan (Zeichnen, Verschieben, Suchtreffer-Markierung, Maschinen platzieren) | nach dem Umzug, sobald das Layout feststeht |
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
- `APP_VERSION` wird von Martin manuell hochgesetzt (aktuell 1.50), nicht automatisch.

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
  angelegt werden, bekommen `M00/E00/P00` beim nächsten Aufruf des Moduls.
- **Nummern bleiben stabil:** Wird eine Ebene oder Position gelöscht, rücken die übrigen nicht
  nach (aufgedruckte Etiketten würden sonst falsch).
- Der Menüpunkt «Inventar» erscheint nur, wenn das Modul in den Einstellungen (Admin) eingeschaltet ist.

## 11b. Stand Etappe 2: Maschinen, Suche, Backup

- **Zuordnung:** `machines.area_id` (ohne DB-FK) ist der massgebliche Bereich; `machines.location` (Text) bleibt für die
  bisherigen Ansichten (Maschinenliste, CSV, Display) erhalten. **Beide werden in Einklang gehalten:**
  - Das Maschinenformular, CSV-Import und Restore schreiben nur den Text. `area_id` wird daraus nachgezogen
    (Gross-/Kleinschreibung egal; Text ohne passenden Bereich bleibt als Text, die Maschine gilt als «ohne Bereich»;
    leerer Text = kein Bereich). Beim Anlegen und Bearbeiten über das Formular sofort, sonst beim nächsten Aufruf des
    Moduls bzw. beim Start.
  - Im Inventar geschriebene Bereichswechsel setzen `area_id` **und** den Text.
  - **Umbenennen eines Standorts** zieht die Maschinen mit (Text und Zuordnung). Das behebt den bekannten Fehler, dass
    der Text bei den Maschinen nach dem Umbenennen veraltet blieb.
  - Löschen einer Maschine entfernt ihre Platzierung.
- **Bereichswechsel:** `PATCH /api/inventory/machines/{id}` (Power-Manager/Admin), Log `machine_area_changed` mit
  Herkunft und Ziel. Ein «steht auf» passt nur im selben Bereich: beim Wechsel wird es automatisch entfernt, ein Möbel
  aus einem anderen Bereich wird abgelehnt (409), M00 ebenfalls (400).
- **Oberfläche:** Reiter «Maschinen» (Liste mit Bereich und «steht auf» als Auswahl, Filter «Ohne Bereich»; Manager sehen
  nur), Maschinenzahl je Bereich im Strukturbaum, Maschinen-Treffer über der Werkzeugliste, Maschinen in der API-Suche
  (`type: "machine"`, mit Pfad «Laser › Tisch 1»).
- **Keine Etikett-Codes für Maschinen**, wie entschieden: Sie sind über Bereich, Möbel und später den Bauplan auffindbar.
- **«Steht auf» mit Ebene:** Eine Maschine kann auf einem Möbel **und** einer Ebene stehen («Druckerregal › Ebene 2»);
  `inv_placements.level_id` (Migration v1.53, ohne DB-FK), nur gültig zusammen mit dem Möbel und nie E00. Wechselt das Möbel oder der
  Bereich, entfällt die Ebene; beim Löschen von Ebene/Möbel wird die Zuordnung der Maschine bereinigt. Backup: `level` (Ebenennummer).
- **Begriffe:** Bei aktivem Inventar heisst «Standort» im ganzen LabManager **«Bereich»** (Formular, Filter, Tabelle, Schaltfläche,
  Dialoge); ohne Inventar bleibt «Standort». CSV-Spalten behalten ihren Namen (Import-Kompatibilität).
- **Maschinenformular:** Neben «Bereich» steht «Steht auf (Möbel / Ebene)»; die Auswahl zeigt die Möbel des gewählten Bereichs mit ihren
  Ebenen und wird mit dem Formular gespeichert (das Feld kommt aus dem Inventar-Modul, das dafür nachgeladen wird). Beim Anlegen einer
  Maschine wird der **Bereich mit demselben Namen wie die Kategorie vorgewählt** (nur wenn noch keiner gewählt ist).
- **Kategorie und Bereich** sind zwei Angaben: Die Kategorie sagt, *was* die Maschine ist (Filter, Symbole, Statistik, MCP), der Bereich,
  *wo* sie steht (Standort-Code, Suche, Plan). Sie decken sich oft («3D-Druck»), müssen es aber nicht (z.B. CNC-Fräse im Bereich «Holz»).

## 11c. Kategorie aus dem Bereich, Feld «Standort»

Bereich und Kategorie sagten bei den Maschinen dasselbe. Bei **aktivem Inventar** ist deshalb der Bereich das einzige
Ordnungsmerkmal:

- **Kategorie wird abgeleitet:** `machines.category` = Name des Bereichs, ohne Bereich «Sonstiges». Die Spalte bleibt, damit
  Filter, Statistik, Gäste-Ansicht, CSV und MCP unverändert funktionieren. Für jeden Bereich (und «Sonstiges») legt der
  Server die gleichnamige Kategorie an. Umbenennen eines Bereichs benennt die Kategorie mit um, Löschen setzt seine Maschinen
  auf «Sonstiges» (ohne Bereich) und entfernt die unbenutzte Kategorie. Ausgerichtet wird beim Anlegen/Bearbeiten, beim
  Bereichswechsel, nach dem CSV-Import und beim ersten Aufruf des Moduls (`align_categories`).
- **Standort-Text ohne passenden Bereich** zählt als «ohne Bereich» (Text bleibt stehen, Kategorie «Sonstiges»).
- **Oberfläche:** Im Maschinenformular entfallen «Kategorie» und das Bereichs-Dropdown; es gibt ein einziges Feld **«Standort»**
  (Bereich, Möbel oder Ebene, jeweils mit Code, z.B. `LAS · Laser`, `LAS-M01 · Regal 1`). «⚙ Kategorien» und der
  Kategorie-Filter sind ausgeblendet. Der frühere Begriff «Steht auf» heisst überall «Standort».
- Bei ausgeschaltetem Inventar bleibt alles wie bisher: Kategorie und «Standort» (einfache Auswahl der Standortliste) sind
  im Formular sichtbar und frei wählbar; nur Möbel/Ebene gibt es dann nicht. Die zuletzt abgeleiteten Kategorien bleiben stehen.

## 11d. Stand Etappe 3: Gästesicht (seit v1.64 mit Anmeldung)

- **Seite:** `frontend/inventar.html` ist jetzt eine eigenständige, schlanke Seite im Stil der Gast-App (Hell/Dunkel wie
  die übrigen Seiten ohne Login, Handy zuerst, keine Sidebar). Sie ersetzt die frühere Weiterleitung in den LabManager.
  Drei Ansichten, alle über die URL: `?q=…` bzw. leer = Suche mit Übersicht der Bereiche und Möbel, `?code=ELE-M01` = Inhalt
  eines Bereichs, Möbels oder einer Ebene (Werkzeug und darauf stehende Maschinen), `?item=<ID>` = «**gehört nach** …» mit
  grossem Code und Pfad. Damit zeigen die gedruckten QR-Codes (Möbel, Ebenen, Werkzeug) ohne Änderung an den Etiketten auf
  die neue Seite.
- **Schnittstelle:** neuer Router `routers/inventory_public.py`, Präfix `/api/inventory-public`, **nur GET, seit v1.64 nur mit Anmeldung** (Gast- oder Lab-Manager-JWT im `Authorization`-Header, sonst 401):
  `overview`, `search?q=`, `code/{code}`, `items/{id}`. Er nutzt dieselbe Such- und Auflösungslogik wie der interne Router, gibt
  aber nur das Nötige heraus (Name, Beschreibung, Menge, Status, Standort mit Code und Pfad). **Ausgemustertes Werkzeug**
  bleibt verborgen, defektes wird mit «DEFEKT» gezeigt. Maschinen erscheinen mit Name, Kategorie und Pfad, nie mit Status,
  Plug oder Seriennummer. Ist das Modul ausgeschaltet, antworten alle vier Endpunkte mit 404.
- **Gast-App (`index.html`):** Auf dem Scan-Bildschirm (nach der Anmeldung) erscheint «🔎 Wo ist …?» (nur bei aktivem Inventar,
  gesteuert über `inventory_enabled` aus `/api/settings/public`).
- **Anmeldung (Entscheid 2026-10-20, v1.64):** Plan und Werkzeugsuche sind nur noch hinter dem Login erreichbar. `inventar.html` liest das Token
  aus `localStorage` (nur `guest_token`; ein Lab-Manager-Login im selben Browser zählt hier bewusst nicht); fehlt es oder ist es ungültig, geht es zu `/?next=inventar.html?…` und nach der
  Anmeldung (Passwort oder Token-Link) automatisch zurück zum QR-Ziel. Das Grundriss-Bild wird per `fetch` mit Header geladen (kein Token in der URL).
- **Tests:** `tests/test_inventory_public.py` (Suche ohne Login, Code-Ansicht mit Maschinen, Verbergen von Ausgemustertem,
  404 bei ausgeschaltetem Modul).

## 11e. Abgrenzung Maschine / Werkzeug, Buchhaltungsfelder

**Entscheidung (Martin, 2026-10-19):** Ein Gerät ist entweder **Maschine** oder **Werkzeug**, nie beides. Massgebend ist, ob es
einen **Standort** (steht/hängt fest, Bereich, ggf. Möbel und Ebene) oder einen **Platz** (liegt im Schrank, gehört dorthin
zurück, Etikett mit QR) hat. Typisch für Maschinen sind Einweisung, Smart Plug und Wartungsintervall, für Werkzeug fehlen sie
und es gibt oft mehrere Stück. **Versicherung gehört nicht zur Abgrenzung:** Ein versicherter Akkuschrauber ohne Einweisung
mit festem Schrankplatz bleibt Werkzeug.

Dafür tragen Werkzeuge dieselben **optionalen Buchhaltungsfelder** wie Maschinen (Migration v1.54, `inv_items`):
`serial_number`, `purchase_date`, `value_new` (Neuwert **je Stück**), `owner_id` (→ `machine_owners`, ohne DB-FK, wie alle
Verweise im Modul). API: `ItemCreate`/`ItemUpdate`, Filter `GET /inventory/items?valued=true` (nur mit Neuwert). Die
**Inventarliste** (Maschinen-Seite, CSV und Druck; im Dialog wählbar: Maschinen ja/nein, Werkzeug ja/nein, bei Werkzeug «nur mit Neuwert» oder «alle», ausgemustertes nie) enthält Maschinen und Werkzeug (Wert = Neuwert × Menge, Kategorie
«Werkzeug»). Im Backup stehen die Felder je Werkzeug (`owner` als Name, `purchase_date` ISO); ältere Backups ohne die Felder
bleiben importierbar. Auf der öffentlichen Gäste-Seite sind sie nie sichtbar.

Verworfen: Maschinen ebenfalls mit Platz und Etikett auszustatten. Dann wären beide Arten praktisch gleich und die Trennung
überflüssig.

## 11f. Stand Etappe 4: Bauplan

- **Darstellung:** Das **Gebäude** ist eine Grundfläche in **cm** (Standard 15 × 10 m, einstellbar). Darin liegen **Stockwerke**
  (Reiter «EG», «OG» …), auf jedem **Räume** und **Treppen** als Rechtecke, dazu Bereiche (gestrichelte Zonen), Möbel und Maschinen
  (von unten nach oben gezeichnet). Räume anderer Stockwerke erscheinen als schwache Umrisse zur Orientierung. Möbel und Maschinen sind drehbar (0–359°, Beschriftung bleibt
  waagrecht), Bereiche nicht. Raster 100 cm, Einrasten auf 5 cm. Kein Hintergrundbild, kein Massstab-Import (bleibt Etappe 5).
- **Stockwerke, Räume, Treppen (Skizze vom 2026-10-19):** Der Makerspace ist nicht rechteckig und liegt auf zwei Stockwerken.
  Entschieden: **Räume sind Rechtecke** (L-förmige Räume aus zwei Rechtecken), keine freien Umrisse. Tabellen `inv_floors` (Name,
  Reihenfolge) und `inv_rooms` (Stockwerk, Name, `kind` = `raum`|`treppe`, Rechteck, Drehung, bei Treppen `link_floor_id` = Ziel-Stockwerk;
  eine Treppe erscheint auf beiden Stockwerken, Beschriftung mit ↑/↓). Jedes eingezeichnete Element trägt `plan_floor_id`
  (Bereich, Möbel, Maschine; fehlend = erstes Stockwerk). Migration v1.56. Stockwerke lassen sich nur löschen, wenn sie leer
  sind, das letzte nie. Die Suche und die Gästeseite schalten automatisch auf das Stockwerk des Treffers.
- **Speicherung:** in den vorhandenen Spalten `machine_locations.plan_*` (Bereich), `inv_furniture.plan_*` (Möbel),
  `inv_placements.plan_*` (Maschine, unabhängig von «steht auf») und neu `inv_plan` (eine Zeile: Name, Breite, Tiefe; Migration
  v1.55, Tabelle über `create_all`). «Auf dem Plan» heisst: `plan_x/y/w/h` gesetzt. Codes und Zuordnungen hängen nicht am Plan.
- **API:** `GET /api/inventory/plan` (alle Lab Manager), `PUT /api/inventory/plan/room` (Gebäude), `POST|PATCH|DELETE /api/inventory/plan/floors[/{id}]`, `POST|PATCH|DELETE /api/inventory/plan/rooms[/{id}]`,
  `PATCH /api/inventory/plan/{area|furniture|machine}/{id}` mit `{x,y,w,h,rot,floor_id}` oder `{remove:true}` (Power-Manager/Admin; `M00` hat keinen Platz; Werte werden geprüft). Verschieben wird
  **nicht** einzeln protokolliert (Alltag), nur Raumänderungen (`inventory_plan_updated`). Öffentlich:
  `GET /api/inventory-public/plan` (nur Elemente, die schon eingezeichnet sind).
- **Oberfläche:** `frontend/inventory-plan.js` (gemeinsamer SVG-Renderer, bearbeitbar oder nur ansehen) wird vom Inventar-Reiter
  «🗺️ Plan» (Ziehen, Grösse an allen vier Ecken und Kanten, Zahlenfelder, ↻ 90°, «Vom Plan nehmen», Liste «Noch nicht auf dem Plan»
  mit Ziehen oder «＋», Zoom, Suche mit Markierung) und von `inventar.html` geladen. Manager sehen den Plan, ändern darf ihn der Power-Manager.
- **Gäste:** `inventar.html?plan=1` (ganzer Plan), `?plan=ELE-M01` (Möbel/Ebene/Werkzeug-Ort markiert), `?plan=ELE` (Bereich),
  `?machine=<ID>`. Auf dem Handy wird der Plan 2,3× gross gezeichnet und zum Treffer gescrollt. Karten «🗺️ Auf dem Plan zeigen»
  stehen bei Werkzeug und Möbel; Maschinen-Treffer führen auf den Plan. Nicht eingezeichnete Ziele zeigen einen Hinweis.
- **Backup:** Sektion `inventory` enthält `room` (Gebäude), `floors`, `rooms` und die Plan-Rechtecke samt Stockwerkname von Bereichen, Möbeln und Maschinen (`placements`);
  fehlender Planplatz bestehender Möbel wird beim Import ohne «Überschreiben» ergänzt.
- **Zurücksetzen:** `POST /api/inventory/plan/reset` (Power-Manager/Admin, protokolliert) löscht Räume, Treppen und Stockwerke (neu nur «EG») und nimmt alle Elemente vom Plan; Gebäude, Codes, Möbel/Ebenen und Maschinen-Standorte bleiben.
- **Vieleck-Räume, Wände, Türen (Entscheid 2026-10-19):** Räume dürfen beliebige Umrisse haben. `inv_rooms.points` (JSON `[[x,y],…]`, 3–60 Punkte, Migration v1.57; leer = Rechteck) ist die Form, `plan_x/y/w/h` bleiben die Umgebung der Punkte (so funktionieren Ansicht, Einrasten und Verschieben unverändert). Die **Wand ist der Umriss** des Raums. Verschieben oder Skalieren per Rechteck/Zahlen führt die Punkte mit. Im Editor: «In Vieleck umwandeln» (vier Ecken), Ecken ziehen, «+» auf der Kantenmitte fügt eine Ecke ein, Doppelklick löscht eine, «Zu Rechteck» geht zurück. **Türen und Durchgänge** sind `inv_rooms` mit `kind` `tuer`/`durchgang` (Standard 90 × 14 cm, drehbar): eine Lücke in der Wand, bei Türen mit Schwenkbogen. Türen sind spiegelbar (`inv_rooms.flip`, Migration v1.58: Bit 1 = Anschlag links/rechts, Bit 2 = Aufschlag zur anderen Wandseite). Sie gehören zu einem Stockwerk, nicht zu einem bestimmten Raum, erscheinen im Gäste-Plan und im Backup (`points` und `kind`).
- **Hintergrund-Grundriss und Wanddicke (Entscheid 2026-10-19):** Weil Masse aus einem Plan (Innen-/Aussen-/Achsmasse) nie sauber zusammenpassen und Einrasten von Raum an Raum die Wanddicke ignoriert, wird nicht über Einrasten gelöst, sondern über ein **Vorlagenbild**. Pro Stockwerk ein JPG/PNG (`inv_floor_images`, Bild auf höchstens 2400 px verkleinert und als JPEG in der DB gespeichert, Migration v1.59; Lage, Grösse, Deckkraft und Drehung in `inv_floors.bg_*`, Migration v1.60 für `bg_rot`; das Bild dreht um seine Mitte, frei in Grad). Massstab: zwei Punkte anklicken, echten Abstand eingeben; dann verschieben und Deckkraft einstellen. Räume werden darüber per Klick auf die Ecken gezeichnet («Raum zeichnen»); mit **Shift oder Strg** rastet die Linie bei 0/90/180/270° ein (Alt: 45°), beim Ziehen einer Ecke werden beide anliegenden Wände rechtwinklig. Das Bild wird im Editor mit Anmeldung geladen (`GET /api/inventory/plan/floors/{id}/background`), Gäste sehen es über `GET /api/inventory-public/plan/floors/{id}/background` (ohne Anmeldung, nur wenn das Inventar aktiv ist; Entscheid 2026-10-19: der Plan der Gäste-Seite zeigt den Grundriss ebenfalls). **Die Ansicht folgt dem Ausschnitt:** der sichtbare Bereich ist der (gedrehte) Ausschnitt des Bildes plus alles, was darüber hinausragt, nicht mehr das ganze Gebäude; Beschriftungen und Hervorhebungen wachsen mit der Ansicht. Gäste sehen die Räume dezent (dünner Umriss), die Wände stehen im Bild. **Zoom auf der Gäste-Seite:** `InvPlan.mount(..., { zoomControls: true })` startet mit dem ganzen Plan (Breite des Feldes, höchstens ca. 2/3 der Fensterhöhe), bietet ＋ − ⤢, Pinch (Touch-Events mit `preventDefault`, damit iOS nicht die ganze Seite zoomt) und Strg+Mausrad, Zoom 1–8×; bei einem Treffer wird auf ×2,2 zum Ziel gezoomt, mit − oder ⤢ wieder heraus. **Wanddicke:** `inv_plan.wall_cm` ist der Standard, **0 = nur Umriss** (neu der Standardwert, weil beim Abpausen die Wände im Bild stehen und eine einheitliche Dicke nicht zu echten Gebäuden passt); `inv_rooms.wall_cm` überschreibt ihn je Raum (Migration v1.61, leer = Standard). Die Wand wird als Rand **ausserhalb** der Raum-Innenfläche gezeichnet; Türen schneiden sie durch. Im Backup enthalten (Bild als Base64 je Stockwerk, `wall_cm`).
- **Rückgängig und Ausschnitt:** **Rückgängig** (Knopf und Strg+Z, höchstens 50 Schritte) ist rein clientseitig: Jede Änderung merkt sich den Stand davor (Rechteck, Eckpunkte, Stockwerk bzw. die Eigenschaften eines Raums, beim Löschen alle Daten zum Wiederherstellen) und stellt ihn über dieselben API-Aufrufe wieder her. Nicht rückgängig: Stockwerke, Bild hochladen/entfernen, Zurücksetzen (der Stapel wird dabei geleert). **Ausschnitt:** `inv_floors.bg_crop_l/t/r/b` (Migration v1.62) sind Anteile (0–0,95) der Bildkanten, die weggeschnitten werden; das Bild bleibt vollständig gespeichert, die Anzeige schneidet per Clip-Pfad zu. Der Ausschnitt wird als Rechteck im Plan aufgezogen und ins Bildsystem zurückgerechnet (auch bei gedrehtem Bild).
- **Layout (Bedienung):** Der Plan nimmt die volle Breite und eine feste Höhe ein (die Seite scrollt beim Zeichnen nicht). Werkzeugleiste «Zeichnen» über dem Plan, Hinweiszeile mit fester Höhe (kein Springen der Fläche), Länge und Winkel der aktuellen Strecke am Mauszeiger. Rechte Spalte: oben die Auswahl, darunter einklappbare Abschnitte (Noch nicht auf dem Plan, Grundriss, Stockwerke, Gebäude, Zurücksetzen).
- **Bewusst nicht:** Wanddicke je Wand, Wand-Netz mit automatischer Raumerkennung, Undo, PDF als Vorlage. Wenn der neue Raum feststeht, reicht es,
  den Raum einzustellen und die Elemente neu zu ziehen.

## 12. Offene Punkte

1. **Fotos:** Wo liegen die Bilder (eigenes Volume `inventory_media`)? JSON-Backup enthält
   sie nicht; es braucht ein separates Sicherungs- und Restore-Verfahren oder den
   Verzicht in Etappe 1.
2. ~~Positionen ohne Fachteiler~~ → entschieden: 0-Regel (`P00`), siehe Abschnitt 3.
3. ~~Token-Teilung~~ → erledigt: Das Modul läuft im LabManager und teilt dessen Anmeldung.
4. ~~Etiketten: Format und Grösse~~ → entschieden: vorgeschnittene A4-Bögen (Avery L6009-20), siehe 7b.
   Offen: Raster am echten Bogen bestätigen.
5. **Verbrauchsmaterial und Akkus:** Die vorhandene Akku-Verwaltung (`batteries`, eigene
   Seite unter AUSSTATTUNG) bleibt getrennt. Sollen Akkus später auch einen Standort
   bekommen (`position_id` an `batteries`)? Da Akkus als loser Pool gelten,
   wäre das eine nullable Ergänzung ohne Umbau.
6. **Mehrfachstandorte** (Werkzeug in mehreren Schränken): bewusst nicht vorgesehen.
