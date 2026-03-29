# ESP32 + PN532 NFC-Schreibgerät — Firmware-Spezifikation

Dieses Dokument enthält alle Informationen, die Claude Code auf dem Windows-PC benötigt,
um die Firmware für das NFC-Schreibgerät zu entwickeln.

---

## Kontext

SpaceCaptain ist ein webbasiertes Zugangs- und Verwaltungssystem für einen Makerspace.
Gäste erhalten Zugang zu Maschinen, indem sie einen **QR-Code** an der Maschine scannen.
Ziel: Dieselbe URL soll alternativ auf einem **NFC-Tag** hinterlegt werden, damit Smartphones
den Tag einfach antippen können (kein Kamera-Scan nötig).

Das ESP32-Gerät steht als **WLAN-Schreibstation** im Makerspace. Der Lab Manager öffnet
im SpaceCaptain-Browser-Interface einen Dialog, wählt die zu beschreibende URL (Maschine
oder Login-Link), legt einen NFC-Tag ans PN532-Modul — fertig.

---

## Hardware

| Komponente | Modell |
|---|---|
| Mikrocontroller | ESP32 (bevorzugt) oder ESP8266 |
| NFC-Modul | PN532 |
| Schnittstelle | I2C (einfachste Verdrahtung) |

### Verdrahtung PN532 → ESP32 (I2C)

| PN532 Pin | ESP32 Pin | Hinweis |
|---|---|---|
| VCC | 3.3V | Nicht 5V! |
| GND | GND | |
| SDA | GPIO 21 | Standard I2C SDA |
| SCL | GPIO 22 | Standard I2C SCL |

**PN532 DIP-Schalter für I2C:** SEL0 = ON, SEL1 = OFF

### NFC-Tags

NTAG213 (144 Byte Nutzlast) ist ausreichend.
Die zu schreibende URL hat max. ~80 Zeichen — passt problemlos.

---

## Funktionsbeschreibung Firmware

### Ablauf

```
1. ESP32 startet → verbindet sich mit WLAN
2. ESP32 wartet auf HTTP-Anfrage von SpaceCaptain
3. SpaceCaptain sendet POST /write mit der zu schreibenden URL
4. ESP32 antwortet sofort: {"status": "waiting"} (Tag noch nicht da)
5. ESP32 wartet bis zu 30 Sekunden auf einen NFC-Tag
6. Wenn Tag erkannt: URL als NDEF URI Record schreiben
7. LED/Status-Feedback (grün = Erfolg, rot = Fehler/Timeout)
8. ESP32 ist bereit für den nächsten Schreibvorgang
```

### Statusanzeige (LED oder Serial)

| Zustand | LED |
|---|---|
| Bereit / wartet auf Auftrag | Blau blinkend (langsam) |
| Wartet auf Tag | Gelb blinkend (schnell) |
| Schreiben erfolgreich | Grün (2 Sekunden) |
| Fehler / Timeout | Rot (2 Sekunden) |

---

## HTTP-API des ESP32

Der ESP32 stellt einen minimalen HTTP-Server bereit.
SpaceCaptain kommuniziert direkt mit der IP des ESP32 im lokalen Netz.

### `GET /status`

Gibt den aktuellen Gerätezustand zurück.

**Response:**
```json
{
  "status": "ready",
  "device": "SpaceCaptain NFC Writer",
  "ip": "10.10.1.xxx"
}
```

`status` kann sein: `"ready"` | `"writing"` | `"error"`

---

### `POST /write`

Startet einen Schreibauftrag. Der ESP32 wartet danach auf einen NFC-Tag.

**Request (JSON):**
```json
{
  "url": "https://10.10.1.245/?m=abc123def456",
  "label": "Lasercutter XL-40"
}
```

**Response — sofort (202 Accepted):**
```json
{
  "status": "waiting",
  "message": "Tag ans Gerät halten",
  "timeout_sec": 30
}
```

**Fehler (409 Conflict) — wenn bereits ein Auftrag läuft:**
```json
{
  "status": "busy",
  "message": "Schreibvorgang läuft bereits"
}
```

---

### `GET /result`

SpaceCaptain pollt diesen Endpoint alle 1–2 Sekunden nach einem `POST /write`,
um das Ergebnis zu erfahren.

**Response — noch am Warten:**
```json
{
  "status": "waiting",
  "elapsed_sec": 5
}
```

**Response — Erfolg:**
```json
{
  "status": "success",
  "message": "Tag erfolgreich beschrieben",
  "url": "https://10.10.1.245/?m=abc123def456"
}
```

**Response — Timeout oder Fehler:**
```json
{
  "status": "error",
  "message": "Timeout — kein Tag erkannt"
}
```

---

## NDEF-Format

Der NFC-Tag muss einen **NDEF URI Record** enthalten.
Das ist das Standardformat, das iOS und Android nativ erkennen und
die URL automatisch im Browser öffnen.

### URI-Präfix-Encoding

NDEF URI Records verwenden einen 1-Byte-Präfix zur Kompression:

| Byte | Präfix |
|---|---|
| `0x00` | (kein Präfix) |
| `0x01` | `http://www.` |
| `0x02` | `https://www.` |
| `0x03` | `http://` |
| `0x04` | `https://` |

Für SpaceCaptain-URLs (`https://10.10.1.245/...`) → Präfix `0x04`, Rest der URL dahinter.

### Adafruit PN532 Bibliothek (Arduino)

```cpp
#include <Wire.h>
#include <Adafruit_PN532.h>

// NDEF URI Record manuell aufbauen:
// TNF = 0x01 (Well Known)
// Type = "U" (0x55)
// Payload: [URI-Präfix-Byte] + [URL als ASCII]

void writeNdefUrl(const String& url) {
    String payload_str = url;
    uint8_t uri_prefix = 0x00;

    // https:// erkennen und Präfix setzen
    if (url.startsWith("https://")) {
        uri_prefix = 0x04;
        payload_str = url.substring(8); // "https://" abschneiden
    } else if (url.startsWith("http://")) {
        uri_prefix = 0x03;
        payload_str = url.substring(7);
    }

    uint8_t payload_len = 1 + payload_str.length(); // Präfix-Byte + URL
    uint8_t record_len  = 1 + 1 + 1 + payload_len;  // TNF+Flags, TypeLen, PayloadLen, Payload
    uint8_t ndef_len    = record_len + 2;             // + 0x03 (NDEF) + 0xFE (Terminator)

    // NDEF-Nachricht aufbauen
    std::vector<uint8_t> ndef;
    ndef.push_back(0x03);           // NDEF Message TLV Tag
    ndef.push_back(record_len + 1); // Length (TNF byte + type_len + payload_len + type + payload)

    // NDEF Record Header
    ndef.push_back(0xD1);           // MB=1, ME=1, CF=0, SR=1, IL=0, TNF=001 (Well Known)
    ndef.push_back(0x01);           // Type Length = 1
    ndef.push_back(payload_len);    // Payload Length
    ndef.push_back('U');            // Type = "U" (URI)

    // Payload
    ndef.push_back(uri_prefix);
    for (char c : payload_str) ndef.push_back((uint8_t)c);

    ndef.push_back(0xFE);           // Terminator TLV

    // Auf Tag schreiben (NTAG213: ab Seite 4, je 4 Byte pro Seite)
    // ... (siehe vollständige Implementierung unten)
}
```

### Empfohlene Bibliothek

**Elechouse PN532** ist oft einfacher für NDEF:
- GitHub: `elechouse/PN532`
- Unterstützt I2C, SPI, HSU
- Hat `NdefMessage` und `NdefRecord` Klassen

```cpp
#include <PN532_I2C.h>
#include <PN532.h>
#include <NdefMessage.h>

PN532_I2C pn532i2c(Wire);
PN532 nfc(pn532i2c);

void writeUrl(const String& url) {
    NdefMessage message;
    message.addUriRecord(url);  // Erledigt Präfix-Encoding automatisch

    uint8_t uid[7];
    uint8_t uidLen;

    if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLen, 5000)) {
        bool success = nfc.writeNdefMessage(uid, uidLen, message);
        // success = true → geschrieben
    }
}
```

---

## SpaceCaptain-Server

### URL-Struktur der zu schreibenden Tags

**Maschinen-Tags:**
```
https://10.10.1.245/?m={qr_token}
```
Beispiel: `https://10.10.1.245/?m=a1b2c3d4e5f6...`

**Login-Link-Tags (Gast):**
```
https://10.10.1.245/?lt={login_token}
```

**Login-Link-Tags (Lab Manager):**
```
https://10.10.1.245/labmanager.html?lt={login_token}
```

### API-Endpoint (wird noch implementiert)

SpaceCaptain wird folgenden Endpoint bereitstellen, über den der Lab Manager
einen Schreibauftrag auslöst:

```
POST https://10.10.1.245/api/nfc/write
Authorization: Bearer {jwt_token}

{
  "url":   "https://10.10.1.245/?m=abc123",
  "label": "Lasercutter XL-40"
}
```

SpaceCaptain kennt die IP des ESP32 aus einer Konfiguration (`.env` oder
Einstellung im UI). SpaceCaptain leitet den Auftrag dann an den ESP32 weiter.

---

## Empfohlene Arduino-Bibliotheken

| Bibliothek | Zweck | Installieren über |
|---|---|---|
| `Adafruit PN532` | PN532-Treiber | Arduino Library Manager |
| `elechouse/PN532` | PN532 + NDEF | GitHub / ZIP-Import |
| `ESPAsyncWebServer` | Async HTTP-Server | GitHub |
| `AsyncTCP` | Abhängigkeit von ESPAsyncWebServer | GitHub |
| `ArduinoJson` | JSON parsen/erstellen | Arduino Library Manager |
| `WiFi` | WLAN (bereits in ESP32-Core) | — |

---

## Firmware-Konfiguration (config.h)

```cpp
// WLAN
#define WIFI_SSID     "MakerSpace-WLAN"
#define WIFI_PASSWORD "wlan-passwort"

// NFC
#define PN532_SDA     21
#define PN532_SCL     22
#define WRITE_TIMEOUT 30000  // ms — wie lange auf Tag warten

// LED-Pins (optional, falls vorhanden)
#define LED_BLUE      2
#define LED_GREEN     4
#define LED_RED       5
```

---

## Projektstruktur (PlatformIO empfohlen)

```
nfc-writer/
├── platformio.ini
├── src/
│   ├── main.cpp
│   ├── nfc_writer.cpp / .h
│   └── web_server.cpp / .h
└── include/
    └── config.h
```

### platformio.ini

```ini
[env:esp32dev]
platform  = espressif32
board     = esp32dev
framework = arduino
lib_deps  =
    adafruit/Adafruit PN532
    bblanchon/ArduinoJson
    esphome/ESPAsyncWebServer-esphome
monitor_speed = 115200
```

---

## Sicherheitshinweise

- Der ESP32 ist nur im **lokalen Makerspace-WLAN** erreichbar, nicht von aussen
- Keine Authentifizierung auf dem ESP32 nötig (Netzwerk-Isolation reicht)
- SpaceCaptain prüft die Berechtigung bevor er den Schreibauftrag weiterleitet
- NFC-Tags können überschrieben werden — kein Passwortschutz nötig für diesen Anwendungsfall

---

## Offene Punkte (SpaceCaptain-seitig, wird separat implementiert)

- [ ] Konfiguration der ESP32-IP in SpaceCaptain (`.env` oder UI-Einstellung)
- [ ] Button "NFC-Tag beschreiben" neben "QR-Code anzeigen" in der Maschinen-Ansicht
- [ ] Polling von `/result` im Frontend während Schreibvorgang
- [ ] Proxy-Endpoint `POST /api/nfc/write` (SpaceCaptain → ESP32)

Diese Punkte werden auf dem Ubuntu-Server implementiert, sobald die ESP32-Firmware steht.
