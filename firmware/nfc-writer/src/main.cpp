#include <Arduino.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include <FastLED.h>
#include "config.h"
#include "nfc_writer.h"
#include "web_server.h"

// ─── Globaler Zustand ─────────────────────────────────────────────────────────

AppState  appState;
NfcWriter nfcWriter(PN532_SDA, PN532_SCL);
NfcHttpServer httpServer(appState, 80);

// ─── WS2812B LED ──────────────────────────────────────────────────────────────

static CRGB _led[1];

static void ledColor(CRGB color) {
    _led[0] = color;
    FastLED.show();
}

static void ledsOff() {
    ledColor(CRGB::Black);
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
                ledColor(_blinkOn ? CRGB::Blue : CRGB::Black);
            }
            break;
        }
        case DeviceState::WAITING: {
            // Gelb, schnell blinkend
            if (now - _lastBlink >= BLINK_FAST) {
                _lastBlink = now;
                _blinkOn   = !_blinkOn;
                ledColor(_blinkOn ? CRGB::Yellow : CRGB::Black);
            }
            break;
        }
        case DeviceState::SUCCESS:
            ledColor(CRGB::Green);
            break;
        case DeviceState::ERROR:
            ledColor(CRGB::Red);
            break;
    }
}

// ─── WLAN verbinden (WiFiManager) ────────────────────────────────────────────

static void connectWifi() {
    WiFiManager wm;
    wm.setConfigPortalTimeout(WIFI_TIMEOUT);

    // Callback: AP gestartet → lila leuchten
    wm.setAPCallback([](WiFiManager*) {
        Serial.printf("[WiFi] Kein WLAN gespeichert – AP \"%s\" gestartet\n", WIFI_AP_NAME);
        ledColor(CRGB::Purple);
    });

    // Verbinden oder Konfigurationsportal starten
    if (!wm.autoConnect(WIFI_AP_NAME, strlen(WIFI_AP_PASS) ? WIFI_AP_PASS : nullptr)) {
        Serial.println("[WiFi] Konfiguration fehlgeschlagen – Neustart");
        ledColor(CRGB::Red);
        delay(3000);
        ESP.restart();
    }

    Serial.printf("[WiFi] Verbunden – IP: %s\n", WiFi.localIP().toString().c_str());
}

// ─── Setup ────────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    Serial.println("\n[Boot] SpaceCaptain NFC Writer startet...");

    // WS2812B initialisieren
    FastLED.addLeds<WS2812B, LED_PIN, GRB>(_led, 1);
    FastLED.setBrightness(LED_BRIGHTNESS);
    ledsOff();

    connectWifi();

    if (!nfcWriter.begin()) {
        Serial.println("[Boot] PN532 nicht gefunden – Neustart in 5s");
        ledColor(CRGB::Red);
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
        Serial.println("[WiFi] Verbindung verloren – Neustart...");
        delay(1000);
        ESP.restart();
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
