#include "web_server.h"
#include <ArduinoJson.h>
#include <WiFi.h>

// ─── Konstruktor ──────────────────────────────────────────────────────────────

WebServer::WebServer(AppState& state, uint16_t port)
    : _server(port), _state(state) {}

// ─── Hilfsmakro: CORS-Header setzen ──────────────────────────────────────────

static void addCors(AsyncWebServerResponse* res) {
    res->addHeader("Access-Control-Allow-Origin",  "*");
    res->addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res->addHeader("Access-Control-Allow-Headers", "Content-Type");
}

// ─── Server starten ───────────────────────────────────────────────────────────

void WebServer::begin() {
    // OPTIONS-Preflight für CORS
    _server.on("/*", HTTP_OPTIONS, [](AsyncWebServerRequest* req) {
        AsyncWebServerResponse* res = req->beginResponse(204);
        addCors(res);
        req->send(res);
    });

    // GET /status
    _server.on("/status", HTTP_GET, [this](AsyncWebServerRequest* req) {
        handleGetStatus(req);
    });

    // GET /result
    _server.on("/result", HTTP_GET, [this](AsyncWebServerRequest* req) {
        handleGetResult(req);
    });

    // POST /write — body wird über den Body-Handler empfangen
    _server.on("/write", HTTP_POST,
        // onRequest (aufgerufen nach vollständigem Body-Empfang)
        [](AsyncWebServerRequest*) {},
        // onUpload  (nicht verwendet)
        nullptr,
        // onBody
        [this](AsyncWebServerRequest* req, uint8_t* data, size_t len,
               size_t index, size_t total) {
            handlePostWrite(req, data, len, index, total);
        }
    );

    // 404 für alle anderen Pfade
    _server.onNotFound([](AsyncWebServerRequest* req) {
        AsyncWebServerResponse* res = req->beginResponse(404, "application/json",
                                                         "{\"error\":\"not found\"}");
        addCors(res);
        req->send(res);
    });

    _server.begin();
    Serial.println("[HTTP] Server gestartet auf Port 80");
}

// ─── GET /status ──────────────────────────────────────────────────────────────

void WebServer::handleGetStatus(AsyncWebServerRequest* req) {
    JsonDocument doc;

    switch (_state.state) {
        case DeviceState::READY:
        case DeviceState::SUCCESS:
        case DeviceState::ERROR:
            doc["status"] = "ready";
            break;
        case DeviceState::WAITING:
            doc["status"] = "writing";
            break;
    }

    doc["device"] = "SpaceCaptain NFC Writer";
    doc["ip"]     = WiFi.localIP().toString();

    String body;
    serializeJson(doc, body);

    AsyncWebServerResponse* res = req->beginResponse(200, "application/json", body);
    addCors(res);
    req->send(res);
}

// ─── POST /write ──────────────────────────────────────────────────────────────

// Statischer Akku-Puffer, um den Body über mehrere Chunks hinweg zu sammeln.
// ESPAsyncWebServer ruft onBody ggf. mehrfach auf (chunked transfer).
static String _bodyAccum;

void WebServer::handlePostWrite(AsyncWebServerRequest* req,
                                uint8_t* data, size_t len,
                                size_t index, size_t total) {
    // Ersten Chunk: Puffer zurücksetzen
    if (index == 0) _bodyAccum = "";

    for (size_t i = 0; i < len; i++) _bodyAccum += (char)data[i];

    // Noch nicht vollständig empfangen
    if (index + len < total) return;

    // ── Gerät beschäftigt? ──────────────────────────────────────────────────
    if (_state.state == DeviceState::WAITING) {
        JsonDocument err;
        err["status"]  = "busy";
        err["message"] = "Schreibvorgang läuft bereits";
        String body;
        serializeJson(err, body);
        AsyncWebServerResponse* res = req->beginResponse(409, "application/json", body);
        addCors(res);
        req->send(res);
        return;
    }

    // ── JSON parsen ─────────────────────────────────────────────────────────
    JsonDocument doc;
    DeserializationError parseErr = deserializeJson(doc, _bodyAccum);
    if (parseErr || !doc["url"].is<String>()) {
        AsyncWebServerResponse* res = req->beginResponse(400, "application/json",
            "{\"error\":\"Ungültiger JSON-Body oder fehlende 'url'\"}");
        addCors(res);
        req->send(res);
        return;
    }

    // ── Auftrag einstellen ──────────────────────────────────────────────────
    _state.pendingUrl   = doc["url"].as<String>();
    _state.pendingLabel = doc["label"] | "";
    _state.jobStartMs   = millis();
    _state.state        = DeviceState::WAITING;
    _state.newJob       = true;

    Serial.printf("[HTTP] Schreibauftrag: %s (\"%s\")\n",
                  _state.pendingUrl.c_str(), _state.pendingLabel.c_str());

    // ── 202 Accepted ────────────────────────────────────────────────────────
    JsonDocument resp;
    resp["status"]      = "waiting";
    resp["message"]     = "Tag ans Gerät halten";
    resp["timeout_sec"] = WRITE_TIMEOUT / 1000;

    String body;
    serializeJson(resp, body);

    AsyncWebServerResponse* res = req->beginResponse(202, "application/json", body);
    addCors(res);
    req->send(res);
}

// ─── GET /result ──────────────────────────────────────────────────────────────

void WebServer::handleGetResult(AsyncWebServerRequest* req) {
    JsonDocument doc;

    switch (_state.state) {
        case DeviceState::WAITING: {
            uint32_t elapsed = (millis() - _state.jobStartMs) / 1000;
            doc["status"]      = "waiting";
            doc["elapsed_sec"] = elapsed;
            break;
        }
        case DeviceState::SUCCESS:
            doc["status"]  = "success";
            doc["message"] = "Tag erfolgreich beschrieben";
            doc["url"]     = _state.resultUrl;
            break;
        case DeviceState::ERROR:
            doc["status"]  = "error";
            doc["message"] = _state.errorMsg;
            break;
        case DeviceState::READY:
            // Kein laufender Auftrag
            doc["status"]  = "idle";
            doc["message"] = "Kein aktiver Schreibauftrag";
            break;
    }

    String body;
    serializeJson(doc, body);

    AsyncWebServerResponse* res = req->beginResponse(200, "application/json", body);
    addCors(res);
    req->send(res);
}
