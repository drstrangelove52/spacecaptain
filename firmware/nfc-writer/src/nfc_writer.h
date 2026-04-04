#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PN532.h>

// Ergebnis eines Schreibvorgangs
enum class NfcWriteResult {
    SUCCESS,
    TIMEOUT,         // Kein Tag innerhalb des Zeitlimits erkannt
    WRITE_ERROR,     // Tag erkannt, Schreiben fehlgeschlagen
    WRONG_TAG_TYPE   // Kein NTAG213/215/216 (z.B. MIFARE Classic)
};

class NfcWriter {
public:
    NfcWriter(uint8_t sda, uint8_t scl);

    // Initialisiert den PN532. Gibt false zurück, wenn kein PN532 gefunden.
    bool begin();

    // Wartet auf einen NFC-Tag und schreibt die URL als NDEF URI Record.
    // timeoutMs: maximale Wartezeit in Millisekunden
    // Nicht-blockierend im Sinne der LED-Updates — ruft ledTickFn() regelmäßig auf.
    NfcWriteResult writeUrl(const String& url, uint32_t timeoutMs,
                            std::function<void()> ledTickFn = nullptr);

    bool isReady() const { return _ready; }

private:
    Adafruit_PN532 _nfc;
    bool _ready = false;

    // Baut den vollständigen NDEF-Bytepuffer für eine URI auf.
    // Gibt die Länge zurück, schreibt in buf (muss groß genug sein).
    static uint16_t buildNdefUri(const String& url, uint8_t* buf, uint16_t bufSize);
};
