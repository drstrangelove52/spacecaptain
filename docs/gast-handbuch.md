# SpaceCaptain — Gäste-Handbuch

Dieses Handbuch erklärt, wie du als Gast des Makerspaces die SpaceCaptain-App verwendest, um Maschinen zu starten und zu beenden.

---

## Inhaltsverzeichnis

1. [Voraussetzungen](#1-voraussetzungen)
2. [Anmeldung](#2-anmeldung)
3. [Maschine starten](#3-maschine-starten)
4. [Maschine beenden](#4-maschine-beenden)
5. [Maschinenübersicht](#5-maschinenübersicht)
6. [Kein Zugang](#6-kein-zugang)
7. [Leerlauf-Abschaltung](#7-leerlauf-abschaltung)
8. [Passwort ändern](#8-passwort-ändern)
9. [Abmelden](#9-abmelden)
10. [Häufige Fragen](#10-häufige-fragen)

---

## 1. Voraussetzungen

- Ein **Smartphone** oder Tablet mit Browser und Kamera
- Ein **Gast-Account** (wird vom Lab Manager angelegt)
- **Berechtigung** für die gewünschte Maschine (wird vom Lab Manager erteilt)

Du benötigst **keine App-Installation** — SpaceCaptain läuft direkt im Browser.

> **Tipp:** Speichere `https://ihr-server/` als Lesezeichen oder füge die Seite zum Startbildschirm hinzu (im Browser-Menü: "Zum Startbildschirm hinzufügen").

---

## 2. Anmeldung

### Standard-Anmeldung

1. Öffne `https://ihr-server/` auf deinem Smartphone
2. Gib **Benutzername** und **Passwort** ein (erhältst du vom Lab Manager)
3. Tippe auf **Anmelden**

<!-- SCREENSHOT: Anmeldemaske Gast -->

> **Hinweis:** Wenn du direkt einen QR-Code an einer Maschine scannst, siehst du vor der Anmeldung bereits die Maschinenkarte — du kannst dich dann direkt für diese Maschine anmelden.

<!-- SCREENSHOT: Anmeldemaske mit Maschinenkarte -->

### Anmeldung mit Link

Falls dir der Lab Manager einen persönlichen Login-Link zugeschickt hat, öffne diesen Link im Browser. Du wirst automatisch angemeldet, ohne Passwort.

---

## 3. Maschine starten

### Schritt 1: QR-Code scannen

Nach der Anmeldung siehst du den Warte-Bildschirm. Gehe zur gewünschten Maschine und scanne den QR-Code, der an der Maschine befestigt ist.

<!-- SCREENSHOT: Warte-Bildschirm nach Anmeldung -->

> **So scannst du:** Dein Smartphone-Browser fragt nach Kamera-Berechtigung — tippe auf **Erlauben**. Halte dann die Kamera auf den QR-Code.

Alternativ kannst du die Maschinen-URL direkt eingeben, falls der Lab Manager sie dir mitgeteilt hat.

### Schritt 2: Maschinenstatus prüfen

Nach dem Scan siehst du die Maschinenkarte:

<!-- SCREENSHOT: Maschinen-Kontrollscreen (Zugang erteilt) -->

Die Karte zeigt:
- **Maschinenname** und Kategorie
- **Status** — ● ONLINE / ○ OFFLINE / ⚠ WARTUNG
- **Aktueller Nutzer** — falls die Maschine gerade von jemand anderem benutzt wird
- **Stromverbrauch** — falls ein Smart Plug angeschlossen ist
- **Hinweis-Kommentar** — falls der Lab Manager eine Notiz hinterlegt hat (z. B. Sicherheitshinweise)

### Schritt 3: Einschalten

Tippe auf **⚡ EINSCHALTEN**.

Die smarte Steckdose schaltet sich ein (sofern konfiguriert), und die Sitzung beginnt. Du siehst nun die Laufzeit und den Stromverbrauch in Echtzeit.

<!-- SCREENSHOT: Maschine läuft — Laufzeit und Verbrauchsanzeige -->

> **Wichtig:** Stelle sicher, dass die Maschine sicher eingerichtet ist, **bevor** du einschaltest.

---

## 4. Maschine beenden

Wenn du fertig bist:

1. Tippe auf **○ AUSSCHALTEN**
2. Die Steckdose schaltet sich aus
3. Du siehst eine Zusammenfassung: Laufzeit und verbrauchte Energie (falls verfügbar)

<!-- SCREENSHOT: Sitzungsende mit Zusammenfassung -->

> **Wichtig:** Schalte die Maschine immer über die App aus — nicht nur den Stromschalter an der Maschine. Nur so wird die Sitzung korrekt protokolliert und anderen Gästen angezeigt, dass die Maschine wieder frei ist.

---

## 5. Maschinenübersicht

Tippe auf **Maschinen-Status anzeigen**, um alle Maschinen zu sehen, für die du eine Berechtigung hast.

<!-- SCREENSHOT: Maschinenübersicht / Dashboard Gast -->

Die Liste zeigt für jede Maschine:
- Status (online / offline / in Betrieb)
- Wer die Maschine gerade benutzt (falls belegt)
- Aktueller Stromverbrauch (falls Smart Plug verbunden)

Tippe auf eine Maschine, um direkt zum Kontrollscreen zu wechseln.

---

## 6. Kein Zugang

Falls du keine Berechtigung für eine Maschine hast, erscheint der Bildschirm **Kein Zugang**:

<!-- SCREENSHOT: "Kein Zugang"-Bildschirm -->

Falls der Lab Manager beim Entziehen der Berechtigung einen Kommentar hinterlassen hat, wird dieser hier angezeigt (z. B. "Sicherheitsunterweisung noch ausstehend").

**Was tun?** Wende dich an einen Lab Manager, um die Berechtigung zu erhalten.

---

## 7. Leerlauf-Abschaltung

Wenn eine Maschine mit Leerlauferkennung konfiguriert ist und über längere Zeit kaum Strom verbraucht (z. B. weil du vergessen hast, sie auszuschalten), schaltet das System automatisch ab.

Kurz vor der automatischen Abschaltung erscheint eine **Warnung** auf deinem Bildschirm:

<!-- SCREENSHOT: Leerlauf-Warnung mit Countdown -->

Die Warnung zeigt einen Countdown. Wenn die Maschine wieder aktiv wird (Stromverbrauch steigt), verschwindet die Warnung automatisch.

---

## 8. Passwort ändern

1. Auf dem Warte-Bildschirm (nach dem Einloggen): Tippe auf **Passwort ändern**
2. Gib dein **aktuelles Passwort** ein
3. Gib dein **neues Passwort** ein (mindestens 6 Zeichen)
4. **Neues Passwort bestätigen**
5. Tippe auf **Passwort speichern**

<!-- SCREENSHOT: Passwort ändern -->

> **Passwort vergessen?** Wende dich an einen Lab Manager — er kann dir ein temporäres Passwort setzen.

---

## 9. Abmelden

Tippe auf dem Warte-Bildschirm auf **Abmelden**. Die Sitzung wird beendet.

Auf dem Maschinen-Kontrollscreen findest du das Abmelden-Symbol oben rechts (⎋).

> **Hinweis:** Die Anmeldung läuft nach 8 Stunden automatisch ab.

---

## 10. Häufige Fragen

**Ich sehe den QR-Code, aber meine Kamera öffnet sich nicht.**

Stelle sicher, dass du dem Browser die Kamera-Berechtigung erteilt hast. iPhone: Einstellungen → Safari → Kamera → Erlauben. Android: Browser-Einstellungen → Berechtigungen → Kamera.

---

**Die Maschine schaltet sich nicht ein, obwohl ich Zugang habe.**

Mögliche Ursachen:
- Die Maschine ist gerade von jemand anderem in Benutzung — warte, bis sie frei ist
- Der Smart Plug ist nicht erreichbar (Netzwerkproblem) — informiere einen Lab Manager
- Die Maschine ist auf "Offline" oder "Wartung" gesetzt — informiere einen Lab Manager

---

**Ich habe vergessen, die Maschine auszuschalten.**

Kehre zur App zurück und schalte die Maschine über **○ AUSSCHALTEN** aus. Wenn die App-Session abgelaufen ist, melde dich erneut an.

Falls du keinen Zugang mehr hast, wende dich an einen Lab Manager — er kann die Session von seiner Seite beenden.

---

**Die App zeigt mir eine Maschine, die ich nicht benutzen darf.**

In der Maschinenübersicht siehst du nur Maschinen, für die du eine Berechtigung hast. Wenn du eine Maschine vermisst, bitte den Lab Manager, dir Zugang zu erteilen.

---

**Mein Passwort funktioniert nicht mehr.**

Wende dich an einen Lab Manager. Er kann dir ein neues temporäres Passwort setzen, das du anschliessend selbst ändern kannst.
