#include "nfc_writer.h"

// ─── Konstruktor ──────────────────────────────────────────────────────────────

NfcWriter::NfcWriter(uint8_t sda, uint8_t scl) : _nfc(-1, -1) {
    Wire.begin(sda, scl);
}

// ─── Initialisierung ──────────────────────────────────────────────────────────

bool NfcWriter::begin() {
    _nfc.begin();
    uint32_t versionData = _nfc.getFirmwareVersion();
    if (!versionData) {
        Serial.println("[NFC] PN532 nicht gefunden");
        return false;
    }
    Serial.printf("[NFC] PN532 gefunden – Firmware v%d.%d\n",
                  (versionData >> 16) & 0xFF,
                  (versionData >>  8) & 0xFF);
    _nfc.SAMConfig();
    _ready = true;
    return true;
}

// ─── NDEF-Puffer aufbauen ─────────────────────────────────────────────────────
//
// Struktur des erzeugten Puffers (NTAG-kompatibel, ab Seite 4):
//
//   0x03  [L]  0xD1  0x01  [PL]  'U'  [prefix]  [url-bytes...]  0xFE  0x00...
//   ^^^^  ^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^  ^^^
//   NDEF  len  NDEF Record                                         Term.
//
// Der Puffer wird auf ein Vielfaches von 4 Bytes aufgefüllt (Seitengröße NTAG).

uint16_t NfcWriter::buildNdefUri(const String& url, uint8_t* buf, uint16_t bufSize) {
    uint8_t uriPrefix = 0x00;
    String  rest      = url;

    if (url.startsWith("https://")) {
        uriPrefix = 0x04;
        rest = url.substring(8);
    } else if (url.startsWith("http://")) {
        uriPrefix = 0x03;
        rest = url.substring(7);
    }

    // Längenprüfung: NDEF Short Record erlaubt max. 255 Byte Payload
    // Payload = URI-Präfix-Byte (1) + URL-Rest
    if (rest.length() > 254) {
        Serial.printf("[NFC] URL zu lang (%d Zeichen nach Präfix, max. 254)\n", rest.length());
        return 0;
    }

    uint8_t  payloadLen = 1 + (uint8_t)rest.length();

    // NDEF Record: TNF+Flags(1) + TypeLen(1) + PayloadLen(1) + Type(1) + Payload
    uint8_t  recordLen  = 1 + 1 + 1 + 1 + payloadLen;

    // TLV wrapper: 0x03 + length-byte + record + 0xFE
    uint16_t msgLen     = 1 + 1 + recordLen + 1;

    // Auf Vielfaches von 4 auffüllen (Seitengröße)
    uint16_t total = (msgLen + 3) & ~3;

    if (total > bufSize) {
        Serial.printf("[NFC] NDEF-Puffer zu klein (%d Bytes benötigt, %d verfügbar)\n",
                      total, bufSize);
        return 0;
    }

    memset(buf, 0x00, total);

    uint16_t i = 0;
    buf[i++] = 0x03;         // NDEF Message TLV Tag
    buf[i++] = recordLen;    // TLV Length

    // NDEF Record Header
    buf[i++] = 0xD1;         // MB=1, ME=1, CF=0, SR=1, IL=0, TNF=001
    buf[i++] = 0x01;         // Type Length = 1
    buf[i++] = payloadLen;   // Payload Length
    buf[i++] = 'U';          // Type = "U" (URI)

    // Payload
    buf[i++] = uriPrefix;
    for (uint16_t j = 0; j < rest.length(); j++) {
        buf[i++] = (uint8_t)rest[j];
    }

    buf[i++] = 0xFE;         // Terminator TLV

    return total;
}

// ─── Tag-Kapazität aus Capability Container ermitteln ────────────────────────

static uint16_t detectTagCapacity(Adafruit_PN532& nfc) {
    uint8_t cc[4] = {0};
    if (!nfc.ntag2xx_ReadPage(3, cc)) return 144;  // Fallback: NTAG213

    switch (cc[2]) {
        case 0x3E: Serial.println("[NFC] NTAG215 erkannt (504 Bytes)"); return 504;
        case 0x6D: Serial.println("[NFC] NTAG216 erkannt (888 Bytes)"); return 888;
        default:   Serial.println("[NFC] NTAG213 erkannt (144 Bytes)"); return 144;
    }
}

// ─── Tag schreiben ────────────────────────────────────────────────────────────

NfcWriteResult NfcWriter::writeUrl(const String& url, uint32_t timeoutMs,
                                   std::function<void()> ledTickFn) {
    Serial.printf("[NFC] Warte auf Tag (max %u ms) für URL: %s\n",
                  timeoutMs, url.c_str());

    uint8_t uid[7];
    uint8_t uidLen = 0;
    uint32_t start = millis();

    while (millis() - start < timeoutMs) {
        if (ledTickFn) ledTickFn();

        // Kurze Timeout-Scheibe: 500 ms pro Versuch, damit ledTickFn regelmäßig aufgerufen wird
        bool found = _nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A,
                                              uid, &uidLen, 500);
        if (!found) continue;

        Serial.printf("[NFC] Tag erkannt – UID-Länge %d\n", uidLen);

        // UID-Länge prüfen: NTAG213/215/216 haben immer 7 Bytes
        // MIFARE Classic hat 4 Bytes
        if (uidLen != 7) {
            Serial.printf("[NFC] Falsche Tag-Typ (UID-Länge %d) – nur NTAG213/215/216 unterstützt\n", uidLen);
            return NfcWriteResult::WRONG_TAG_TYPE;
        }

        // Tag-Kapazität ermitteln und NDEF-Puffer entsprechend aufbauen
        uint16_t capacity = detectTagCapacity(_nfc);
        const uint16_t MAX_BUF = 892;  // NTAG216 max
        uint8_t ndefBuf[MAX_BUF];
        uint16_t ndefLen = buildNdefUri(url, ndefBuf, min(capacity, MAX_BUF));
        if (ndefLen == 0) return NfcWriteResult::WRITE_ERROR;

        // NDEF-Puffer seitenweise schreiben (ab Seite 4, je 4 Byte)
        uint16_t pages = (ndefLen + 3) / 4;
        for (uint16_t p = 0; p < pages; p++) {
            uint8_t pageData[4];
            memcpy(pageData, ndefBuf + p * 4, 4);
            if (!_nfc.ntag2xx_WritePage(4 + p, pageData)) {
                Serial.printf("[NFC] Schreiben fehlgeschlagen bei Seite %d\n", 4 + p);
                return NfcWriteResult::WRITE_ERROR;
            }
        }

        Serial.println("[NFC] Tag erfolgreich beschrieben");
        return NfcWriteResult::SUCCESS;
    }

    Serial.println("[NFC] Timeout – kein Tag erkannt");
    return NfcWriteResult::TIMEOUT;
}
