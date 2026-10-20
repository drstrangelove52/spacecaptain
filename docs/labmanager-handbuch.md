# SpaceCaptain — Lab-Manager-Handbuch

Dieses Handbuch richtet sich an **Lab Manager** und **Administratoren**, die das SpaceCaptain-System verwalten.

---

## Inhaltsverzeichnis

1. [Anmeldung](#1-anmeldung)
2. [Dashboard](#2-dashboard)
3. [Gäste verwalten](#3-gäste-verwalten)
4. [Lab Manager verwalten](#4-lab-manager-verwalten)
5. [Maschinen verwalten](#5-maschinen-verwalten)
   - [5a. Inventar & Standorte](#5a-inventar--standorte)
6. [Berechtigungen](#6-berechtigungen)
7. [QR-System](#7-qr-system)
8. [Aktivitätslog](#8-aktivitätslog)
9. [Statistiken](#9-statistiken)
10. [Maschinenpflege](#10-maschinenpflege)
11. [Backup und Wiederherstellung](#11-backup-und-wiederherstellung)
12. [Info](#12-info)
13. [Rollen und Rechte](#13-rollen-und-rechte)
14. [Smarte Steckdosen](#14-smarte-steckdosen)
15. [Häufige Aufgaben](#15-häufige-aufgaben)

---

## 1. Anmeldung

Die Lab-Manager-Oberfläche ist erreichbar unter:

```
https://ihr-server/labmanager.html
```

> **Hinweis:** Die Sitzung ist 8 Stunden gültig. Danach ist eine erneute Anmeldung erforderlich.

<!-- SCREENSHOT: Anmeldemaske Lab Manager -->

**Felder:**
- **E-Mail** — Die bei der Benutzererstellung vergebene E-Mail-Adresse
- **Passwort** — Das persönliche Passwort

Nach erfolgreicher Anmeldung wird das Dashboard angezeigt. In der linken Seitenleiste ist die Navigation sowie die aktuelle Systemversion sichtbar.

---

## 2. Dashboard

Das Dashboard gibt einen sofortigen Überblick über den aktuellen Systemzustand.

<!-- SCREENSHOT: Dashboard-Gesamtansicht -->

### Statistik-Kacheln

Vier farbige Kacheln zeigen die wichtigsten Kennzahlen auf einen Blick:

| Kachel | Inhalt |
|---|---|
| **Gäste** (orange) | Gesamtzahl der angelegten Gast-Accounts |
| **Maschinen** (cyan) | Gesamtzahl der erfassten Maschinen |
| **Lab Manager** (grün) | Anzahl aktiver Lab-Manager-Accounts |
| **Berechtigungen** (rot) | Gesamtzahl erteilter Zugänge (Gast × Maschine) |

### Aktive Maschinen

Wenn gerade Maschinen in Betrieb sind, erscheint dieser Bereich automatisch. Er zeigt:
- Maschinenname und Kategorie
- Aktueller Benutzer und Laufzeit
- Stromverbrauch (falls Smart Plug verbunden)

### Wartungshinweise

Sind Wartungsintervalle fällig oder bald fällig, erscheinen hier rote bzw. orange Warnkarten. Ein Klick öffnet direkt die Maschinenpflege-Seite.

### Alle Maschinen — Status

Tabelle mit allen Maschinen und deren aktuellem Zustand:

| Spalte | Beschreibung |
|---|---|
| **Status** | ● ONLINE / ○ OFFLINE / ⚠ WARTUNG |
| **Kategorie** | Icon und Maschinentyp |
| **Name** | Maschinenname |
| **Adapter** | EIN / AUS / OFFLINE / — (kein Adapter) |
| **Benutzer** | Aktuell aktiver Gast oder Lab Manager |

### Aktivitätsvorschau

Die letzten Systemereignisse werden unterhalb der Maschinentabelle angezeigt.

---

## 3. Gäste verwalten

Unter **Gäste** werden alle Makerspace-Mitglieder verwaltet, die Zugang zu Maschinen benötigen.

<!-- SCREENSHOT: Gästeliste -->

### Gast anlegen

1. Schaltfläche **+ Gast anlegen** klicken
2. Formular ausfüllen:
   - **Name** *(Pflichtfeld)* — Vollständiger Name
   - **Benutzername** *(Pflichtfeld, eindeutig)* — Für den Login auf dem Gastgerät
   - **E-Mail** *(optional)* — Muss eindeutig sein, falls angegeben
   - **Telefon** *(optional)*
   - **Passwort** *(Pflichtfeld)* — Mindestens 6 Zeichen
   - **Notiz** *(optional)* — Interne Bemerkung (nur für Lab Manager sichtbar)
3. **Speichern** klicken

<!-- SCREENSHOT: Modal "Gast anlegen" -->

### Gast bearbeiten

Über das **Stift-Symbol** neben einem Gast können alle Felder nachträglich geändert werden. Das Passwortfeld bleibt leer — nur ausfüllen, wenn es geändert werden soll.

> **Passwort vergessen:** Das Passwort eines Gastes kann hier neu gesetzt und dem Gast persönlich mitgeteilt werden. Der Gast kann es anschliessend selbst unter Einstellungen ändern.

### Gast deaktivieren / löschen

- **Deaktivieren** (Status-Toggle): Der Gast kann sich nicht mehr einloggen, seine Daten und Berechtigungen bleiben erhalten.
- **Löschen** (Papierkorb-Symbol): Entfernt den Account dauerhaft. Berechtigungen werden ebenfalls gelöscht. Aktivitätslogs bleiben erhalten (Gast-Referenz wird auf *gelöscht* gesetzt).

### Login-Token

Für jeden Gast kann ein **tokenbasierter Login-Link** erstellt werden:

1. Gast in der Liste auswählen → **Token-Symbol** klicken
2. Es wird ein Link generiert: `https://ihr-server/?token=...`
3. Diesen Link dem Gast zukommen lassen (z. B. per E-Mail oder QR-Code)

Der Gast kann diesen Link verwenden, ohne ein Passwort einzugeben. Der Token ist 365 Tage gültig. Mit **Token widerrufen** wird er sofort ungültig.

> **Sicherheitshinweis:** Behandle Login-Links wie Passwörter — wer den Link hat, kann sich einloggen.

---

## 4. Lab Manager verwalten

Unter **Lab Manager** werden die Mitarbeiter verwaltet, die das System administrieren.

<!-- SCREENSHOT: Lab-Manager-Liste -->

### Rollen

| Rolle | Rechte |
|---|---|
| **Admin** | Vollzugriff: kann alle Benutzer erstellen, bearbeiten, löschen und Rollen ändern |
| **Manager** | Kann Gäste, Maschinen und Berechtigungen verwalten; kann nur das eigene Profil bearbeiten |

### Lab Manager anlegen *(nur Admin)*

1. **+ Lab Manager anlegen** klicken
2. Formular ausfüllen:
   - **Name**, **E-Mail** *(eindeutig)*, **Passwort**
   - **Rolle** — Admin oder Manager
   - **Telefon** *(optional)*
   - **Bereich** *(optional)* — z. B. "Holzwerkstatt", "Elektronik"
3. **Speichern** klicken

### Lab Manager löschen *(nur Admin)*

Ein eigener Account kann nicht gelöscht werden. Mindestens ein Admin muss immer im System verbleiben.

---

## 5. Maschinen verwalten

Unter **Maschinen** wird der gesamte Maschinenpark erfasst und verwaltet.

<!-- SCREENSHOT: Maschinenübersicht (Grid) -->

### Ansicht und Filter

- **Suchfeld** — Filtert nach Maschinenname
- **Kategorie-Filter** — Laser, CNC, 3D-Druck, Holz, Metall, Elektronik, Sonstiges
- **Status-Filter** — Online, In Betrieb, Offline, Wartung

Jede Maschine wird als Karte angezeigt mit:
- Kategorie-Icon und Name
- Statusbadge (farbiger Punkt)
- Anzahl berechtigter Gäste
- Aktuelle Sitzung (falls aktiv)
- Echtzeit-Adapter-Status (falls Smart Plug verbunden)

### Maschine anlegen

1. **+ Maschine anlegen** klicken
2. Grunddaten ausfüllen:
   - **Name** *(Pflichtfeld)*
   - **Kategorie** — entfällt bei aktivem Inventar-Modul (ergibt sich aus dem Standort, siehe [5a](#5a-inventar--standorte))
   - **Hersteller** / **Modell** *(optional)*
   - **Standort** *(optional)* — z. B. "Raum A, links"; bei aktivem Inventar-Modul der **Bereich**, optional mit Möbel und Ebene
   - **Status** — Online / Offline / Wartung
   - **Kommentar** *(optional)* — Wird dem Gast bei der Anmeldung angezeigt (z. B. Sicherheitshinweise)
3. **Smart Plug** konfigurieren (optional, siehe [Smarte Steckdosen](#14-smarte-steckdosen))
4. **Leerlauferkennung** konfigurieren (optional):
   - **Leerlauf-Schwellwert (W)** — Unter diesem Wert gilt die Maschine als im Leerlauf
   - **Leerlauf-Timeout (Min)** — Nach dieser Zeit im Leerlauf wird automatisch abgeschaltet
5. **Speichern** klicken

<!-- SCREENSHOT: Modal "Maschine anlegen" -->

### Maschine bearbeiten

Klick auf eine Maschinenkarte öffnet die Detailansicht. Über **Bearbeiten** können alle Felder geändert werden.

### Status manuell setzen

In der Bearbeitungsmaske kann der Status auf **Offline** oder **Wartung** gesetzt werden. Maschinen im Wartungsmodus sind für Gäste nicht zugänglich.

### QR-Token erneuern

Jede Maschine hat einen eindeutigen QR-Token. Über **QR erneuern** wird ein neuer Token generiert — alle bestehenden QR-Code-Ausdrucke werden damit ungültig und müssen neu ausgedruckt werden.

### Maschine löschen

Löscht die Maschine dauerhaft. Alle zugehörigen Berechtigungen werden ebenfalls gelöscht. Aktivitätslogs und Sitzungsaufzeichnungen bleiben erhalten.

---

## 5a. Inventar & Standorte

Das optionale **Inventar-Modul** beantwortet zwei Fragen: *«Wo ist …?»* (Gäste finden Werkzeug und Maschinen selbst) und *«Wohin gehört …?»* (Werkzeug landet nicht im falschen Schrank). Es wird von einem **Admin** unter Einstellungen → System → **Inventar-Modul** eingeschaltet; danach erscheint in der Sidebar der Punkt **Inventar**. Ausgeschaltet bleibt alles unsichtbar.

### Maschine oder Werkzeug?

Jedes Gerät steht entweder als **Maschine** oder als **Werkzeug** im System, nie doppelt. Die Trennung hängt an der Frage, ob es einen *Standort* oder einen *Platz* hat:

| | Maschine | Werkzeug |
|---|---|---|
| Wo? | **Standort**: steht oder hängt fest (Bereich, ggf. auf Tisch/Regal und Ebene) | **Platz**: liegt im Schrank und gehört dorthin zurück |
| Etikett | kein Etikett-Code | Etikett mit Code und QR («gehört nach …») |
| Typisch | Einweisung, Smart Plug, Wartungsintervall | keine Einweisung, oft mehrere Stück |
| Erfasst unter | Sidebar → Maschinen | Inventar → Werkzeug |

**Versichern ist ein eigenes Thema:** Kaufdatum, Neuwert, Seriennummer und Eigentümer lassen sich bei beiden erfassen. Beim Werkzeug sind sie optional (Formularabschnitt «Buchhaltung / Versicherung»), z. B. für einen versicherten Akkuschrauber. Der Neuwert gilt **je Stück**; solche Geräte werden einzeln geführt, nicht als Sammelmenge. Die **📋 Inventarliste** (Maschinen-Seite) fragt im Dialog, was hinein soll: **Maschinen** und/oder **Werkzeug**, bei Werkzeug «nur mit erfasstem Neuwert» (Versicherung) oder «alle Werkzeuge» (Bestandsliste); Ausgabe als CSV oder Druck, mit Summe.

**Faustregel für Handgeräte** (Akkuschrauber, Stichsäge, Lötstation): ohne Einweisung und mit festem Schrankplatz ist es Werkzeug; braucht es Einweisung, Plug oder Wartungsintervall, ist es eine Maschine.

### Der Code

Ein Code beschreibt einen Ort von gross nach klein, z. B. `ELE-M02-E03-P04`:

| Teil | Bedeutung |
|---|---|
| `ELE` | **Bereich** (genau 3 Zeichen, z. B. Elektronik) |
| `M02` | **Möbel** 2: Schrank, Regal, Werkzeugwand oder Tisch |
| `E03` | **Ebene** 3, von oben nach unten gezählt |
| `P04` | **Platz** 4, von links nach rechts gezählt |

Alle Nummern sind zweistellig. **00** heisst «nicht unterteilt oder noch nicht festgelegt» (`M00` = im Bereich ohne Möbel, `E00` = Ebene offen, `P00` = kein fester Platz). Auf Etiketten entfallen abschliessende Nullen; `ELE-M02` steht für das ganze Möbel.

### Einrichten *(Power-Manager und Admin)*

1. **Bereiche** sind die bisherigen Standorte (dieselbe Liste, Maschinen → **⚙ Bereiche**). Jeder Bereich braucht ein **Kürzel** aus 3 Zeichen (wird vorgeschlagen) und kann eine Farbe haben. Ein geändertes Kürzel ändert alle Codes darunter; die Etiketten gelten dann als «veraltet».
2. Inventar → **Struktur** → **+ Möbel**: Art, Name und Anzahl Ebenen/Plätze angeben.
3. Löschen ist nur möglich, wenn nichts mehr daran hängt.

### Werkzeug erfassen

Inventar → **Werkzeug** → **+ Werkzeug**: Name, Synonyme (z. B. «Bohrschrauber»), Menge, Status (aktiv, defekt, ausgemustert), Standort (Code tippen oder Bereich → Möbel → Ebene → Platz wählen), Beschreibung. Mehrere auf einmal: Inventar → **Import** (eine Zeile pro Werkzeug: `Name ; Synonyme ; Code ; Menge`, aus Excel einfügbar, mit «Prüfen» vorab).

### Maschinen: Standort statt Kategorie

Bei aktivem Inventar ersetzt der **Bereich** die Kategorie:

- Im Maschinenformular gibt es nur den **Standort** (Bereich, optional Möbel und Ebene, mit Code).
- Die **Kategorie** wird automatisch abgeleitet (gleicher Name wie der Bereich, ohne Bereich «Sonstiges»). **⚙ Kategorien** und der Kategoriefilter entfallen.
- Einen Bereich **umzubenennen** zieht Maschinen und Kategorie mit; ihn zu **löschen** setzt seine Maschinen auf «Sonstiges».
- Inventar → **Maschinen** zeigt alle Maschinen mit Standort und erlaubt das schnelle Umstellen (auch «Ohne Bereich»).
- Beim Ausschalten des Moduls erscheinen Kategorie und einfaches Standort-Dropdown wieder; die zuletzt abgeleiteten Kategorien bleiben bestehen.

### Bauplan

Inventar → **Plan** zeigt das Gebäude von oben (Masse in cm), Stockwerk für Stockwerk (Reiter «EG», «OG» …), mit Räumen, Treppen, Bereichen (gestrichelt), Möbeln und Maschinen. Ansehen und Suchen darf jeder Lab Manager, **Zeichnen** der Power-Manager und der Admin.

1. Rechts unter **Gebäude** die Grundfläche in Metern einstellen und unter **Stockwerke** «EG», «OG» usw. anlegen.
2. Pro Stockwerk mit der Leiste **Zeichnen** über dem Plan (✏️ Raum zeichnen, ▭ Rechteck, 🚪 Tür, ⬚ Durchgang, 🪜 Treppe) Räume und Treppen anlegen. Ein Raum beginnt als Rechteck; **In Vieleck umwandeln** erlaubt beliebige Formen (Ecken ziehen, «+» an einer Kante fügt eine Ecke ein, Doppelklick auf eine Ecke löscht sie). Mit **+ Tür** und **+ Durchgang** setzt du Türen (mit Schwenkbogen) und Öffnungen in die Wand; Drehung und Breite stellst du bei der Auswahl ein; **Anschlag spiegeln** setzt das Scharnier auf die andere Seite, **Aufschlag spiegeln** lässt die Tür zur anderen Wandseite aufgehen. Eine Treppe wird über «Verbindet mit» einem zweiten Stockwerk zugeordnet und erscheint auf beiden.
3. Aus **«Noch nicht auf dem Plan»** ein Element auf die Fläche ziehen (oder **＋** für die Mitte); es landet auf dem gewählten Stockwerk.
4. **Verschieben** durch Ziehen (rastet auf 5 cm), **Grösse** an Ecken und Kanten, **genaue Werte**, **Stockwerk wechseln**, **↻ 90°** und **Vom Plan nehmen** rechts bei der Auswahl.
5. Die **Suche** oben markiert Werkzeug, Möbel oder Maschinen auf dem Plan und schaltet auf das richtige Stockwerk.
6. **Rückgängig:** **↶ Rückgängig** (oder **Strg+Z**) nimmt die letzten Änderungen am Plan einzeln zurück (bis zu 50). Nicht rückgängig zu machen: Stockwerke anlegen/löschen, Grundriss-Bild hochladen/entfernen, Plan zurücksetzen.
7. **Ausschnitt:** **✂️ Ausschnitt** (im Abschnitt «Grundriss zum Abpausen») zeigt nur den gewählten Teil des Bildes, zum Beispiel ohne Bemassung am Rand; das Bild bleibt vollständig gespeichert, «Ausschnitt aufheben» zeigt es wieder ganz.
8. **Grundriss abpausen:** Pro Stockwerk lässt sich ein JPG/PNG des Plans hochladen («Grundriss zum Abpausen»). **📏 Massstab setzen**: zwei Punkte anklicken und den echten Abstand in Metern eingeben. **✋ Bild verschieben**, **↻ 90° drehen** bzw. das Feld **Drehung (°)** (auch in Zehntelgrad, für schief gescannte Pläne) und der Regler **Deckkraft** richten das Bild aus. Danach mit **✏️ Raum zeichnen** die Ecken nacheinander anklicken (Doppelklick oder Klick auf die erste Ecke schliesst den Raum). **Shift oder Strg** gedrückt halten lässt die Linie bei 0°, 90°, 180° und 270° einrasten (**Alt**: 45°); beim Ziehen einer Ecke macht dasselbe die anliegenden Wände rechtwinklig. Das Bild (mit dem gewählten Ausschnitt) sehen auch die Gäste im Plan auf «Wo ist …?». Die Ansicht richtet sich nach dem Ausschnitt, nicht nach dem ganzen Gebäude.
9. **Wanddicke:** Räume sind Innenflächen. Standard ist **0 = nur Umriss**, das genügt beim Abpausen, weil die echten Wände im Bild zu sehen sind. Mit einer Dicke (Einstellung «Wanddicke» bei «Gebäude») wird die Wand aussen um den Raum gezeichnet; weil Wände unterschiedlich dick sind, kann jeder Raum bei der Auswahl eine **eigene Wanddicke** bekommen (leer = Standard). Türen schneiden die Wand durch.
10. **Plan zurücksetzen** (rechts bei «Gebäude»): löscht alle Räume, Treppen und Stockwerke (danach nur «EG») und nimmt alle Elemente vom Plan; Gebäude, Codes und Standorte bleiben. Vorher ein Backup machen.
11. **Zoom:** «Einpassen» zeigt den ganzen Plan auf einen Blick, 25–300 % vergrössern oder verkleinern ihn.

Änderungen werden sofort gespeichert. Der Plan ist unabhängig von den Codes; nach einem Umzug genügt es, Gebäude, Stockwerke und Räume neu zu zeichnen und die Elemente neu zu ziehen. Ein Stockwerk lässt sich nur löschen, wenn es leer ist. Gäste sehen den Plan auf der Seite «Wo ist …?» (nur eingezeichnete Elemente).

### Etiketten

Inventar → **Etiketten**: links die Auswahl (Möbel und Ebenen oder Werkzeug) mit **Anzahl**, rechts Vorlage und Vorschau. Vorbereitet ist der **Avery Zweckform L6009-20** (45,7 × 21,2 mm, 48 pro A4-Bogen, Laserdrucker); über die Startposition lassen sich angefangene Bögen weiterverwenden. Drucken in A4 mit 100 % Skalierung, ohne Kopf-/Fusszeilen und Ränder. Vor dem ersten Druck den **Testbogen** auf normales Papier drucken, gegen das Licht über einen Etikettenbogen halten und bei Bedarf den **Versatz X/Y** einstellen. Neue oder geänderte Möbel sind als «Etikett neu/veraltet» markiert.

Der QR-Code führt Gäste zur Seite des Ortes bzw. des Werkzeugs («gehört nach …»); er bleibt nach dem Umlagern gültig.

### Gäste-Seite «Wo ist …?»

`/inventar.html` ist eine schlanke Seite, die eine **Anmeldung** braucht (Gast-App oder Lab Manager; Scannt jemand den QR-Code ohne Anmeldung, geht es zuerst zum Login und dann zurück) (zusätzlich als «🔎 Wo ist …?» in der Gast-App). Sie zeigt nur Name, Beschreibung, Menge, Status und Standort; ausgemustertes Werkzeug ist verborgen, Maschinen erscheinen ohne Status, Plug oder Seriennummer, Buchhaltungsfelder nie. Ist das Modul ausgeschaltet, antwortet sie mit «nicht aktiviert».

### Rechte im Inventar

| Funktion | Manager | Power-Manager | Admin |
|---|:---:|:---:|:---:|
| Suchen, ansehen | ✅ | ✅ | ✅ |
| Werkzeug anlegen, bearbeiten, umlagern, importieren | ✅ | ✅ | ✅ |
| Bereiche, Möbel, Ebenen, Plätze; Plan zeichnen; Maschinen einem Standort zuweisen | ❌ | ✅ | ✅ |
| Modul ein-/ausschalten | ❌ | ❌ | ✅ |

---

## 6. Berechtigungen

Unter **Berechtigungen** wird gesteuert, welcher Gast welche Maschine benutzen darf.

Die Ansicht hat zwei Tabs:

### 6.1 Gast-Ansicht (Standard)

<!-- SCREENSHOT: Berechtigungen — Gast-Ansicht -->

1. Links: Liste aller Gäste (alphabetisch sortiert, mit Suchfeld)
2. Gast auswählen → rechts erscheinen alle Maschinen mit Schaltern
3. Schalter umlegen = Berechtigung erteilen oder entziehen

> **Pflichtkommentar:** Bei jeder Änderung ist ein Kommentar erforderlich. Dieser wird im Aktivitätslog gespeichert und dem Gast bei einer Zugangsverweigerung angezeigt.

Die rechte Spalte zeigt für jede Maschine:
- Schalter (grün = Zugang erteilt)
- Maschinenname und Kategorie-Icon
- Letzter Kommentar
- Lab Manager, der die letzte Änderung vorgenommen hat
- Zeitstempel der letzten Änderung

### 6.2 Maschinen-Ansicht

1. Tab **⚙ Maschinen-Ansicht** klicken
2. Links: Liste aller Maschinen (mit Suchfeld)
3. Maschine auswählen → rechts erscheinen alle Gäste mit Schaltern

<!-- SCREENSHOT: Berechtigungen — Maschinen-Ansicht -->

### 6.3 Mehrfachauswahl

In der Maschinen-Ansicht steht zusätzlich **☑ Mehrfachauswahl** zur Verfügung:

1. **☑ Mehrfachauswahl** klicken
2. Checkboxen für gewünschte Gäste anhaken
3. Schnellauswahl-Schaltflächen:
   - **Alle** — Alle Gäste auswählen
   - **Keine** — Auswahl aufheben
   - **Aktuell Berechtigte** — Nur bereits berechtigte Gäste auswählen
4. Kommentar eingeben
5. **Speichern** klicken — alle Änderungen werden mit einem einzigen Kommentar gespeichert

> **Anwendungsfall:** Neue Maschine erfasst → Mehrfachauswahl → alle Lab Manager und Grundmitglieder auf einmal berechtigen.

---

## 7. QR-System

Unter **QR-System** werden die QR-Codes für Maschinen erstellt und verwaltet.

<!-- SCREENSHOT: QR-System Übersicht -->

### Workflow

```
1. Gast öffnet https://ihr-server/ auf dem Smartphone
2. Gast meldet sich an
3. Gast scannt den QR-Code an der gewünschten Maschine
4. System prüft Berechtigung
5. Smart Plug schaltet Strom ein (falls konfiguriert)
```

### Maschinen-QR ausdrucken

1. Maschine aus der Dropdown-Liste auswählen
2. **QR-Code anzeigen** klicken
3. Es erscheint ein QR-Code-Bild

<!-- SCREENSHOT: QR-Code Anzeige -->

4. Bild per Rechtsklick speichern oder direkt drucken
5. QR-Code gut sichtbar an der Maschine anbringen

> **Hinweis:** Der QR-Code enthält die URL `https://ihr-server/?m={maschinentoken}`. Nach einem QR-Token-Reset muss der Code neu ausgedruckt werden.

---

## 8. Aktivitätslog

Das Aktivitätslog ist das vollständige Protokoll aller Systemereignisse.

<!-- SCREENSHOT: Aktivitätslog mit Filterleiste -->

### Filter

| Filter | Beschreibung |
|---|---|
| **Gast** | Filtert nach einem bestimmten Gast |
| **Maschine** | Filtert nach einer bestimmten Maschine |
| **Typ** | Filtert nach Ereignistyp |
| **Von / Bis** | Zeitraum einschränken |
| **Suche** | Freitextsuche in der Nachricht |

### Ereignistypen

| Typ | Bedeutung |
|---|---|
| `access_granted` | Gast hat Zugang zu einer Maschine erhalten |
| `access_denied` | Zugang verweigert (keine Berechtigung) |
| `plug_on` / `plug_off` | Steckdose wurde ein- / ausgeschaltet |
| `session_started` | Maschinensitzung gestartet |
| `idle_off` | Automatische Abschaltung wegen Leerlauf |
| `permission_granted` / `permission_revoked` | Berechtigung erteilt / entzogen |
| `guest_created` / `guest_deleted` | Gast-Account angelegt / gelöscht |
| `machine_created` / `machine_deleted` | Maschine angelegt / gelöscht |
| `login` / `guest_login` | Lab-Manager- / Gast-Anmeldung |
| `maintenance_due` / `maintenance_done` | Wartung fällig / durchgeführt |
| `inventory_*` | Inventar: Bereich, Möbel, Ebene bzw. Werkzeug angelegt, geändert, gelöscht, umgelagert oder importiert |
| `machine_area_changed` | Maschine in einen anderen Bereich (Standort) verschoben |
| `inventory_plan_updated` | Gebäude oder Stockwerke des Bauplans geändert |
| `error` | Systemfehler |

---

## 9. Statistiken

Die Statistikseite liefert Nutzungsberichte für einzelne Maschinen oder Gäste über wählbare Zeiträume.

<!-- SCREENSHOT: Statistiken — Ergebnisansicht -->

### Filter

- **Maschine** — Alle oder eine bestimmte Maschine
- **Gast** — Alle oder ein bestimmter Gast
- **Zeitraum** — Letzte 7 Tage / 30 Tage / 90 Tage / 1 Jahr

Nach Klick auf **Auswerten** erscheinen:

### Zusammenfassung

| Kachel | Inhalt |
|---|---|
| **Sitzungen** | Anzahl der Maschinenstarts im gewählten Zeitraum |
| **Laufzeit** | Gesamtstunden im Betrieb |
| **Energie** | Gesamtverbrauch in kWh (nur mit Smart Plug) |
| **Leerlauf-Abschaltungen** | Anzahl automatischer Abschaltungen |

### Betriebsstunden-Tabelle

Zeigt pro Maschine: Gesamtbetriebsstunden, Durchschnittsdauer je Sitzung, Anzahl Sitzungen.

### Sitzungsdetails

Chronologische Liste aller einzelnen Maschinensitzungen mit: Maschine, Gast, Startzeit, Dauer, Energieverbrauch, Beendigungsgrund (manuell / Manager / Leerlauf).

---

## 10. Maschinenpflege

Die Maschinenpflege verwaltet wiederkehrende Wartungsaufgaben.

<!-- SCREENSHOT: Maschinenpflege — Übersicht -->

### Wartungsintervalle

Ein **Wartungsintervall** definiert, wann eine Maschine gewartet werden muss.

#### Intervall anlegen

1. **+ Wartungsintervall** klicken
2. Formular ausfüllen:
   - **Maschine** auswählen
   - **Name** — z. B. "Ölung Linearführung"
   - **Beschreibung** *(optional)*
   - **Intervall** — entweder nach Betriebsstunden *oder* nach Tagen
   - **Warngrenze** — wie weit vor Fälligkeit eine Warnung erscheint

<!-- SCREENSHOT: Modal "Wartungsintervall anlegen" -->

#### Statusanzeige

| Farbe | Status | Bedeutung |
|---|---|---|
| 🔴 Rot | **Fällig** | Wartung überfällig |
| 🟡 Orange | **Warnung** | Wartung bald fällig |
| 🟢 Grün | **OK** | Kein Handlungsbedarf |

Fällige Wartungen erscheinen auch auf dem Dashboard als Warnkarte.

#### Freie Wartung dokumentieren

Über **+ Freie Wartung** kann eine einmalige Wartung dokumentiert werden, ohne ein dauerhaftes Intervall anzulegen.

### Wartungshistorie

Die Wartungshistorie zeigt alle durchgeführten Wartungen mit: Intervallname, Maschine, durchführende Person, Datum, Betriebsstunden zum Zeitpunkt, Notizen.

### Wartung als erledigt markieren

1. Auf das entsprechende Intervall klicken → **Als erledigt markieren**
2. Optional: Notiz eingeben
3. **Speichern** — Der Zähler wird zurückgesetzt, der nächste Fälligkeitstermin berechnet

---

## 11. Backup und Wiederherstellung

Regelmässige Backups sichern alle Systemdaten.

<!-- SCREENSHOT: Backup-Seite -->

> **Sicherheitshinweis:** Die Backup-Datei enthält Passwort-Hashes. Die Datei sicher aufbewahren und nicht unverschlüsselt per E-Mail versenden.

### Export (Datensicherung)

1. **Backup exportieren** klicken
2. Eine `.json`-Datei wird heruntergeladen (enthält alle Daten)
3. Datei sicher verwahren (z. B. verschlüsseltes Laufwerk, lokales NAS)

Die Backup-Datei enthält:
- Alle Benutzer und Gäste (mit Passwort-Hashes)
- Alle Maschinen und QR-Token
- Berechtigungsmatrix
- Sitzungsaufzeichnungen
- Komplettes Aktivitätslog
- Wartungsintervalle und -protokolle
- Kategorien, Standorte (Bereiche), Eigentümer und Akkus
- Inventar (Möbel, Ebenen, Werkzeug mit Buchhaltungsfeldern, Standorte der Maschinen)

### Import (Wiederherstellung)

1. **Backup importieren** → Datei auswählen
2. System prüft die Datei und zeigt eine Vorschau
3. **Import bestätigen**

> **Hinweis:** Der Import ist additiv — bestehende Einträge werden nicht überschrieben, sondern ergänzt. Doppelte Benutzernamen / E-Mails werden übersprungen.

### Empfehlung

- Backup **vor** grossen Änderungen (z. B. Migration, Updates)
- Backup **regelmässig** (z. B. wöchentlich manuell oder per Cron-Job)

---

## 12. Info

Die Info-Seite zeigt:
- Aktuelle Systemversion
- Link zur API-Dokumentation (`/docs`)
- Systemstatus

---

## 12a. Einstellungen → Update *(nur Admin)*

Unter **Einstellungen → 🔄 Update** kann SpaceCaptain direkt aus dem Browser aktualisiert werden, ohne auf den Server einloggen zu müssen.

### Voraussetzung

Der Update-Watcher muss einmalig auf dem Host eingerichtet sein (siehe [README — In-App Update](../README.md#in-app-update-optional)). Das Panel zeigt einen Badge, ob der Watcher aktiv ist.

### Update durchführen

1. **Einstellungen → Update** öffnen
2. Aktuellen Stand (Version + Build-Nr.) prüfen
3. **Update starten** klicken und bestätigen
4. Der Watcher auf dem Host führt automatisch `git pull` + `docker compose up --build backend` aus
5. Der Backend-Container startet neu — die Verbindung unterbricht für wenige Sekunden, danach steht die neue Version bereit

> **Hinweis:** Ein Backup vor dem Update wird empfohlen. DB-Migrationen laufen beim Backend-Start automatisch.

---

## 13. Rollen und Rechte

Es gibt drei Rollen, die **aufeinander aufbauen**: Jede Rolle kann alles, was die darunter kann, und etwas dazu. (Gäste haben ein eigenes System und stehen hier nicht.)

### 13.1 Was kommt mit jeder Rolle dazu?

| Rolle | Darf (zusätzlich) |
|---|---|
| **Manager** (Betrieb) | Gäste verwalten und Berechtigungen vergeben, Maschinen schalten, Raum öffnen/schliessen, Notfall-Alarm, Wartung erfassen, Log und Statistiken ansehen, Werkzeug im Inventar pflegen |
| **+ Power-Manager** (Konfiguration) | Maschinen anlegen/ändern/löschen, CSV-Import, Kategorien/Standorte/Eigentümer, Plug-Pool, Automationen, Aushänge, Wartungsintervalle, Push-Topics, Inventar-Struktur und Bauplan, Maschinen-Standorte |
| **+ Admin** (Systemverwaltung) | Lab Manager anlegen/löschen und Rollen ändern, Backup und Restore, Einstellungen (inkl. Inventar-Modul), In-App-Update |

### 13.2 Rechtetabelle: wer darf was?

| Aktion | Manager | Power-Manager | Admin |
|---|:---:|:---:|:---:|
| **Gäste und Berechtigungen** | | | |
| Gäste anzeigen, freischalten, bearbeiten, anlegen, löschen | ✅ | ✅ | ✅ |
| Berechtigungen vergeben und entziehen | ✅ | ✅ | ✅ |
| Berechtigungsmatrix, Aktivitätslog und Statistiken ansehen | ✅ | ✅ | ✅ |
| **Maschinen** | | | |
| Maschinen anzeigen und schalten (EIN/AUS) | ✅ | ✅ | ✅ |
| Maschinen anlegen, bearbeiten, löschen, QR neu generieren | ❌ | ✅ | ✅ |
| CSV-Import; Kategorien, Standorte, Eigentümer verwalten | ❌ | ✅ | ✅ |
| **Plug-Pool und Automationen** | | | |
| Plug-Pool und Automationen ansehen | ✅ | ✅ | ✅ |
| Plugs anlegen, bearbeiten, löschen, testen, zuweisen | ❌ | ✅ | ✅ |
| Automationen anlegen, bearbeiten, löschen | ❌ | ✅ | ✅ |
| **Maschinenpflege** | | | |
| Wartung erfassen, Übersicht ansehen | ✅ | ✅ | ✅ |
| Wartungsintervalle anlegen, bearbeiten, löschen | ❌ | ✅ | ✅ |
| **Betrieb und Kommunikation** | | | |
| Raum öffnen/schliessen, Notfall-Alarm | ✅ | ✅ | ✅ |
| Eigenes Profil bearbeiten | ✅ | ✅ | ✅ |
| Aushänge verwalten | ❌ | ✅ | ✅ |
| Push-Topics (ntfy) verwalten | ❌ | ✅ | ✅ |
| Warteliste einer Maschine verwalten; NFC-Writer benutzen | ✅ | ✅ | ✅ |
| **Inventar (wenn aktiviert)** | | | |
| Suchen; Werkzeug anlegen, bearbeiten, umlagern, importieren | ✅ | ✅ | ✅ |
| Bereiche, Möbel, Ebenen und Bauplan bearbeiten; Maschinen einem Standort zuweisen | ❌ | ✅ | ✅ |
| Inventar-Modul ein-/ausschalten | ❌ | ❌ | ✅ |
| **System** | | | |
| Lab Manager anlegen, löschen, Rollen ändern | ❌ | ❌ | ✅ |
| Backup und Restore | ❌ | ❌ | ✅ |
| Einstellungen | ❌ | ❌ | ✅ |
| In-App-Update | ❌ | ❌ | ✅ |
| Daten aufräumen (Log, Sessions, Wartungshistorie löschen); NFC-Writer suchen | ❌ | ❌ | ✅ |

Dieselbe Übersicht steht in der App unter **Hilfe → Rollen & Rechte**, dort mit Filter «Was darf Rolle X?».

---

## 14. Smarte Steckdosen

SpaceCaptain unterstützt folgende Smart-Plug-Modelle:

### myStrom Switch

| Feld | Wert |
|---|---|
| **Adapter-Typ** | myStrom |
| **IP-Adresse** | IP-Adresse des Plugs im lokalen Netz |
| **Token** | *(optional)* API-Token des Geräts |

### Shelly Plug (Gen 1)

| Feld | Wert |
|---|---|
| **Adapter-Typ** | Shelly |
| **IP-Adresse** | IP-Adresse des Plugs |
| **Token** | *(optional)* `benutzername:passwort` für Digest-Auth |

### Shelly Plus / Pro (Gen 2)

| Feld | Wert |
|---|---|
| **Adapter-Typ** | Shelly |
| **IP-Adresse** | IP-Adresse des Plugs |
| **Extra** | `gen2` |

### Kein Adapter

Wenn keine smarte Steckdose angeschlossen ist: **Adapter-Typ → Kein**. Sitzungen werden trotzdem protokolliert, aber kein Strom geschaltet.

### Adapter-Status im Dashboard

Wenn ein konfigurierter Adapter nicht erreichbar ist, erscheint in der Maschinenübersicht und im Dashboard **⚠ ADAPTER NICHT ERREICHBAR**. Das ist ein Hinweis auf ein Netzwerkproblem oder ein ausgestecktes Gerät.

---

## 15. Häufige Aufgaben

### Neuen Gast aufnehmen

1. **Gäste** → **+ Gast anlegen** → Daten eingeben
2. **Berechtigungen** → Gast auswählen → Maschinen aktivieren (mit Kommentar)
3. Zugangsdaten (Benutzername, Passwort) dem Gast mitteilen
4. Gast die URL `https://ihr-server/` und den QR-Code an der Maschine zeigen

### Gast sperren (vorübergehend)

**Gäste** → Gast auswählen → **Bearbeiten** → Status auf **Inaktiv** setzen. Der Gast kann sich nicht mehr anmelden. Berechtigungen bleiben erhalten.

### Gast verlässt den Makerspace

1. **Berechtigungen** → alle Berechtigungen entziehen (mit Kommentar)
2. **Gäste** → Gast löschen oder deaktivieren

### Passwort eines Gastes zurücksetzen

**Gäste** → Gast bearbeiten → neues Passwort eingeben → dem Gast persönlich mitteilen. Der Gast kann es anschliessend selbst unter **Einstellungen** ändern.

### Neue Maschine in Betrieb nehmen

1. **Maschinen** → **+ Maschine anlegen** → alle Daten inkl. Smart Plug konfigurieren
2. **QR-System** → Maschine auswählen → QR-Code ausdrucken und an der Maschine befestigen
3. **Berechtigungen** → Maschinen-Ansicht → Maschine auswählen → berechtigte Gäste aktivieren

### Maschine ausser Betrieb nehmen

**Maschinen** → Maschine bearbeiten → Status auf **Wartung** oder **Offline** setzen. Gäste können die Maschine nicht mehr starten.

### Session eines Gastes beenden (Notfall)

**Dashboard** → in der Tabelle "Aktive Maschinen" → Maschine suchen → manuell ausschalten. Die Session wird als "durch Manager beendet" protokolliert.
