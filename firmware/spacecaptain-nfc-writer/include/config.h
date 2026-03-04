#pragma once

// ─── WLAN ────────────────────────────────────────────────────────────────────
#define WIFI_SSID     "MakerSpace-WLAN"
#define WIFI_PASSWORD "wlan-passwort"

// ─── NFC / PN532 (I2C) ────────────────────────────────────────────────────────
#define PN532_SDA     21
#define PN532_SCL     22
#define WRITE_TIMEOUT 30000  // ms — wie lange auf NFC-Tag warten

// ─── LED-Pins ────────────────────────────────────────────────────────────────
// Auf 0 setzen, wenn die jeweilige LED nicht bestückt ist
#define LED_BLUE      2
#define LED_GREEN     4
#define LED_RED       5

// ─── Blink-Intervalle (ms) ────────────────────────────────────────────────────
#define BLINK_SLOW    1000   // Bereit (blau, langsam)
#define BLINK_FAST    250    // Wartet auf Tag (gelb → blau+rot abwechselnd)

// ─── Status-Anzeige-Dauer ─────────────────────────────────────────────────────
#define STATUS_HOLD_MS 2000  // Grün/Rot nach Erfolg/Fehler halten
