# SpaceCaptain — Lab-Manager-Handbuch

Dieses Handbuch richtet sich an **Lab Manager** und **Administratoren**, die das SpaceCaptain-System verwalten.

---

## Inhaltsverzeichnis

1. [Anmeldung](#1-anmeldung)
2. [Dashboard](#2-dashboard)
3. [Gäste verwalten](#3-gäste-verwalten)
4. [Lab Manager verwalten](#4-lab-manager-verwalten)
5. [Maschinen verwalten](#5-maschinen-verwalten)
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
   - **Kategorie**
   - **Hersteller** / **Modell** *(optional)*
   - **Standort** *(optional)* — z. B. "Raum A, links"
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

## 13. Rollen und Rechte

| Funktion | Manager | Admin |
|---|---|---|
| Gäste anzeigen / bearbeiten | ✅ | ✅ |
| Gäste löschen | ✅ | ✅ |
| Maschinen anzeigen / bearbeiten | ✅ | ✅ |
| Berechtigungen verwalten | ✅ | ✅ |
| Eigenes Profil bearbeiten | ✅ | ✅ |
| Lab Manager anlegen / löschen | ❌ | ✅ |
| Rollen anderer Benutzer ändern | ❌ | ✅ |
| Backup exportieren / importieren | ❌ | ✅ |

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
