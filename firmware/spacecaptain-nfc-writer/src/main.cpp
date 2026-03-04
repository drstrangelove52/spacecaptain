#include <Arduino.h>
#include <WiFi.h>
#include "config.h"
#include "nfc_writer.h"
#include "web_server.h"

// ─── Globaler Zustand ─────────────────────────────────────────────────────────

AppState  appState;
NfcWriter nfcWriter(PN532_SDA, PN532_SCL);
WebServer httpServer(appState, 80);

// ─── LED-Hilfsfunktionen ──────────────────────────────────────────────────────

static void ledsOff() {
    if (LED_BLUE)  digitalWrite(LED_BLUE,  LOW);
    if (LED_GREEN) digitalWrite(LED_GREEN, LOW);
    if (LED_RED)   digitalWrite(LED_RED,   LOW);
}

static void ledSet(uint8_t pin, bool on) {
    if (pin) digitalWrite(pin, on ? HIGH : LOW);
}

// Zustandsabhängige LED-Anzeige (wird aus dem Haupt-Loop aufgerufen)
static uint32_t _lastBlink = 0;
static bool     _blinkOn   = false;

static void updateLeds() {
    uint32_t now = millis();

    switch (appState.state) {
        case DeviceState::READY: {
            // Blau, langsam blinkend
            if (now - _lastBlink >= BLINK_SLOW) {
                _lastBlink = now;
                _blinkOn   = !_blinkOn;
                ledsOff();
                ledSet(LED_BLUE, _blinkOn);
            }
            break;
        }
        case DeviceState::WAITING: {
            // Gelb = Rot + Grün, schnell blinkend
            if (now - _lastBlink >= BLINK_FAST) {
                _lastBlink = now;
                _blinkOn   = !_blinkOn;
                ledsOff();
                if (_blinkOn) {
                    ledSet(LED_RED,   true);
                    ledSet(LED_GREEN, true);
                }
            }
            break;
        }
        case DeviceState::SUCCESS:
            ledsOff();
            ledSet(LED_GREEN, true);
            break;
        case DeviceState::ERROR:
            ledsOff();
            ledSet(LED_RED, true);
            break;
    }
}

// ─── WLAN verbinden ───────────────────────────────────────────────────────────

static void connectWifi() {
    Serial.printf("[WiFi] Verbinde mit \"%s\"...\n", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        // Blaue LED blinken während Verbindungsaufbau
        ledsOff();
        ledSet(LED_BLUE, true);
        delay(250);
        ledsOff();
        delay(250);
        if (millis() - start > 30000) {
            Serial.println("[WiFi] Verbindung fehlgeschlagen – Neustart");
            ESP.restart();
        }
    }

    Serial.printf("[WiFi] Verbunden – IP: %s\n", WiFi.localIP().toString().c_str());
}

// ─── Setup ────────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    Serial.println("\n[Boot] SpaceCaptain NFC Writer startet...");

    // LED-Pins initialisieren
    if (LED_BLUE)  { pinMode(LED_BLUE,  OUTPUT); digitalWrite(LED_BLUE,  LOW); }
    if (LED_GREEN) { pinMode(LED_GREEN, OUTPUT); digitalWrite(LED_GREEN, LOW); }
    if (LED_RED)   { pinMode(LED_RED,   OUTPUT); digitalWrite(LED_RED,   LOW); }

    connectWifi();

    if (!nfcWriter.begin()) {
        Serial.println("[Boot] PN532 nicht gefunden – Neustart in 5s");
        ledSet(LED_RED, true);
        delay(5000);
        ESP.restart();
    }

    httpServer.begin();
    Serial.println("[Boot] Bereit");
}

// ─── Loop ─────────────────────────────────────────────────────────────────────

void loop() {
    // WLAN-Verbindung überwachen
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[WiFi] Verbindung verloren – reconnect...");
        connectWifi();
    }

    // LED aktualisieren
    updateLeds();

    // Neuen Schreibauftrag bearbeiten
    if (appState.newJob) {
        appState.newJob = false;

        String url = appState.pendingUrl; // lokale Kopie

        // Callback für LED-Updates während blockierendem NFC-Warten
        NfcWriteResult result = nfcWriter.writeUrl(url, WRITE_TIMEOUT, []() {
            updateLeds();
        });

        switch (result) {
            case NfcWriteResult::SUCCESS:
                appState.resultUrl = url;
                appState.errorMsg  = "";
                appState.state     = DeviceState::SUCCESS;
                Serial.println("[Main] Erfolg");
                break;
            case NfcWriteResult::TIMEOUT:
                appState.errorMsg = "Timeout — kein Tag erkannt";
                appState.state    = DeviceState::ERROR;
                Serial.println("[Main] Timeout");
                break;
            case NfcWriteResult::WRITE_ERROR:
                appState.errorMsg = "Schreibfehler";
                appState.state    = DeviceState::ERROR;
                Serial.println("[Main] Schreibfehler");
                break;
        }

        // LED-Feedback halten (STATUS_HOLD_MS)
        uint32_t holdStart = millis();
        while (millis() - holdStart < STATUS_HOLD_MS) {
            updateLeds();
            delay(50);
        }

        // Zurück auf READY
        appState.state = DeviceState::READY;
        _lastBlink     = 0;
        _blinkOn       = false;
    }

    delay(10);
}
