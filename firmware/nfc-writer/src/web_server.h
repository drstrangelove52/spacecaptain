#pragma once

#include <Arduino.h>
#include <ESPAsyncWebServer.h>

// Gerätezustände
enum class DeviceState {
    READY,    // Wartet auf Schreibauftrag
    WAITING,  // Schreibauftrag aktiv, wartet auf NFC-Tag
    SUCCESS,  // Letzter Schreibvorgang erfolgreich
    ERROR     // Letzter Schreibvorgang fehlgeschlagen / Timeout
};

// Gemeinsamer Zustand zwischen Web-Server-Handlers und Haupt-Loop
struct AppState {
    volatile DeviceState state  = DeviceState::READY;
    volatile bool        newJob = false;   // Trigger für Haupt-Loop

    String  pendingUrl;    // URL des aktuellen Auftrags
    String  pendingLabel;  // Bezeichnung des Auftrags (nur für Logging)
    String  resultUrl;     // URL, die tatsächlich geschrieben wurde
    String  errorMsg;      // Fehlermeldung im Fehlerfall
    uint32_t jobStartMs = 0; // millis() beim Start des Auftrags
};

class NfcHttpServer {
public:
    explicit NfcHttpServer(AppState& state, uint16_t port = 80);
    void begin();

private:
    AsyncWebServer _server;
    AppState&      _state;

    void handleGetStatus (AsyncWebServerRequest* req);
    void handlePostWrite (AsyncWebServerRequest* req, uint8_t* data, size_t len,
                          size_t index, size_t total);
    void handleGetResult (AsyncWebServerRequest* req);
};
