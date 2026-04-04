#include <Arduino.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include <FastLED.h>
#include <ArduinoOTA.h>
#include <ESPmDNS.h>
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

// ─── OTA einrichten ──────────────────────────────────────────────────────────

static void setupOta() {
    ArduinoOTA.setHostname(MDNS_HOSTNAME);

    ArduinoOTA.onStart([]() {
        Serial.println("[OTA] Update startet...");
        ledColor(CRGB::White);
    });
    ArduinoOTA.onEnd([]() {
        Serial.println("[OTA] Update abgeschlossen");
        ledColor(CRGB::Green);
    });
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        Serial.printf("[OTA] %u%%\n", progress * 100 / total);
    });
    ArduinoOTA.onError([](ota_error_t error) {
        Serial.printf("[OTA] Fehler [%u]\n", error);
        ledColor(CRGB::Red);
    });

    ArduinoOTA.begin();
    Serial.printf("[OTA] Bereit – Hostname: %s\n", MDNS_HOSTNAME);
}

// ─── Setup ────────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    Serial.printf("\n[Boot] SpaceCaptain NFC Writer v%s startet...\n", FIRMWARE_VERSION);

    // WS2812B initialisieren
    FastLED.addLeds<WS2812B, LED_PIN, GRB>(_led, 1);
    FastLED.setBrightness(LED_BRIGHTNESS);
    ledsOff();

    connectWifi();

    // mDNS starten (nfc-writer.local)
    if (MDNS.begin(MDNS_HOSTNAME)) {
        MDNS.addService("http", "tcp", 80);
        Serial.printf("[mDNS] %s.local erreichbar\n", MDNS_HOSTNAME);
    } else {
        Serial.println("[mDNS] Start fehlgeschlagen");
    }

    setupOta();

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
    // OTA-Updates verarbeiten
    ArduinoOTA.handle();

    // WLAN-Verbindung überwachen — Reconnect vor Neustart versuchen
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[WiFi] Verbindung verloren – versuche Reconnect...");
        ledColor(CRGB::Purple);
        WiFi.reconnect();

        uint32_t t = millis();
        while (WiFi.status() != WL_CONNECTED && millis() - t < WIFI_RECONNECT_TIMEOUT_MS) {
            ArduinoOTA.handle();
            delay(500);
        }

        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("[WiFi] Reconnect fehlgeschlagen – Neustart");
            delay(1000);
            ESP.restart();
        }

        Serial.printf("[WiFi] Reconnect erfolgreich – IP: %s\n",
                      WiFi.localIP().toString().c_str());
        appState.state = DeviceState::READY;
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
            case NfcWriteResult::WRONG_TAG_TYPE:
                appState.errorMsg = "Falscher Tag-Typ — bitte NTAG213/215/216 verwenden";
                appState.state    = DeviceState::ERROR;
                Serial.println("[Main] Falscher Tag-Typ");
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
