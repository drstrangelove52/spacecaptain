#pragma once

// ─── WLAN ─────────────────────────────────────────────────────────────────────
// Credentials werden über WiFiManager konfiguriert (kein Hardcoding nötig).
// AP-Name beim ersten Boot:
#define WIFI_AP_NAME  "SpaceCaptain-NFC"
#define WIFI_AP_PASS  ""           // leer = offenes AP (für einfaches Onboarding)
#define WIFI_TIMEOUT  180          // Sekunden, bis AP-Modus aufgegeben wird

// ─── NFC / PN532 (I2C) ────────────────────────────────────────────────────────
#define PN532_SDA     21
#define PN532_SCL     22
#define WRITE_TIMEOUT 30000  // ms — wie lange auf NFC-Tag warten

// ─── WS2812B RGB-LED ─────────────────────────────────────────────────────────
#define LED_PIN        2    // Datenpin der WS2812B-LED
#define LED_BRIGHTNESS 50   // Helligkeit 0–255 (50 ≈ augenschonend)

// ─── Blink-Intervalle (ms) ────────────────────────────────────────────────────
#define BLINK_SLOW    1000   // Bereit (blau, langsam)
#define BLINK_FAST    250    // Wartet auf Tag (gelb → blau+rot abwechselnd)

// ─── Status-Anzeige-Dauer ─────────────────────────────────────────────────────
#define STATUS_HOLD_MS 2000  // Grün/Rot nach Erfolg/Fehler halten
