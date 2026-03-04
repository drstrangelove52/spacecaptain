-- SpaceCaptain Datenbank Schema
SET NAMES utf8mb4;
SET time_zone = '+00:00';

-- --------------------------------------------------------
-- Benutzer (Lab Manager / Admins)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    email         VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          ENUM('admin','manager') NOT NULL DEFAULT 'manager',
    phone         VARCHAR(50),
    area          VARCHAR(200),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------
-- Gäste
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS guests (
    id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    username      VARCHAR(80)  NOT NULL UNIQUE,
    email         VARCHAR(150) UNIQUE,
    password_hash VARCHAR(255),
    phone         VARCHAR(50),
    note          TEXT,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------
-- Gäste Login-Token (für QR-Codes, Legacy)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS guest_tokens (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    guest_id    INT UNSIGNED NOT NULL,
    token       VARCHAR(64) NOT NULL UNIQUE,
    expires_at  DATETIME NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (guest_id) REFERENCES guests(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------
-- Maschinen
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS machines (
    id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name              VARCHAR(100) NOT NULL,
    category          VARCHAR(50)  NOT NULL DEFAULT 'Sonstiges',
    manufacturer      VARCHAR(100),
    model             VARCHAR(100),
    location          VARCHAR(200),
    status            ENUM('online','offline','maintenance') NOT NULL DEFAULT 'online',
    -- Smart Plug (nur myStrom und Shelly)
    plug_type         ENUM('mystrom','shelly','none') NOT NULL DEFAULT 'none',
    plug_ip           VARCHAR(50),
    plug_extra        VARCHAR(255),   -- Shelly: 'gen2' für Plus/Pro Modelle
    plug_token        VARCHAR(255),   -- myStrom: API-Token (X-Auth-Token)
    -- Leerlauf-Automatik
    idle_power_w      FLOAT DEFAULT NULL,   -- Leerlaufleistung in Watt
    idle_timeout_min  INT   DEFAULT NULL,   -- Abschalt-Timeout in Minuten
    plug_poll_interval_sec INT UNSIGNED DEFAULT 60, -- Poll-Intervall in Sekunden
    -- Aktive Session
    current_guest_id    INT UNSIGNED DEFAULT NULL,  -- gesetzt wenn Gast aktiv
    session_manager_id  INT UNSIGNED DEFAULT NULL,  -- gesetzt wenn Manager aktiv
    session_started_at  DATETIME DEFAULT NULL,
    -- Sonstiges
    comment           TEXT,
    qr_token          VARCHAR(64) NOT NULL UNIQUE,
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (current_guest_id)   REFERENCES guests(id) ON DELETE SET NULL,
    FOREIGN KEY (session_manager_id) REFERENCES users(id)  ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------
-- Maschinennutzungs-Sessions
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS machine_sessions (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    machine_id      INT UNSIGNED NOT NULL,
    guest_id        INT UNSIGNED,
    started_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at        DATETIME DEFAULT NULL,
    duration_min    FLOAT DEFAULT NULL,       -- Laufzeit in Minuten (nach Ende)
    energy_wh       FLOAT DEFAULT NULL,       -- Verbrauch in Wh (nach Ende)
    ended_by        ENUM('guest','manager','idle_timeout','system') DEFAULT NULL,
    FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE,
    FOREIGN KEY (guest_id)   REFERENCES guests(id)   ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------
-- Berechtigungen
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS permissions (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    guest_id    INT UNSIGNED NOT NULL,
    machine_id  INT UNSIGNED NOT NULL,
    granted_by  INT UNSIGNED,
    granted_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_perm (guest_id, machine_id),
    FOREIGN KEY (guest_id)   REFERENCES guests(id)   ON DELETE CASCADE,
    FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE,
    FOREIGN KEY (granted_by) REFERENCES users(id)    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------
-- Aktivitätslog
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS activity_log (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    type        ENUM('access_granted','access_denied','plug_on','plug_off',
                     'guest_created','guest_deleted','machine_created','machine_deleted',
                     'permission_granted','permission_revoked','login','guest_login','error','idle_off','session_started') NOT NULL,
    guest_id    INT UNSIGNED,
    machine_id  INT UNSIGNED,
    user_id     INT UNSIGNED,
    message     TEXT NOT NULL,
    meta        JSON,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (guest_id)   REFERENCES guests(id)   ON DELETE SET NULL,
    FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id)    REFERENCES users(id)    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------
-- Standard-Admin (Passwort: admin1234 — BITTE ÄNDERN)
-- --------------------------------------------------------
INSERT IGNORE INTO users (name, email, password_hash, role) VALUES (
    'Administrator',
    'admin@spacecaptain.local',
    '$2b$12$u2YsbkDXyEvovgDwCPlUx.wpi.GI6klYGpocKTdKuTOq8Cbv4UcFq',
    'admin'
);

-- --------------------------------------------------------
-- Migration (Upgrade bestehender DBs)
-- --------------------------------------------------------
ALTER TABLE machines ADD COLUMN IF NOT EXISTS plug_token       VARCHAR(255) DEFAULT NULL AFTER plug_extra;
ALTER TABLE machines ADD COLUMN IF NOT EXISTS idle_power_w      FLOAT        DEFAULT NULL AFTER plug_extra;
ALTER TABLE machines ADD COLUMN IF NOT EXISTS idle_timeout_min  INT          DEFAULT NULL AFTER idle_power_w;
ALTER TABLE machines ADD COLUMN IF NOT EXISTS plug_poll_interval_sec INT UNSIGNED DEFAULT 60 AFTER idle_timeout_min;
ALTER TABLE machines ADD COLUMN IF NOT EXISTS current_guest_id   INT UNSIGNED DEFAULT NULL AFTER idle_timeout_min;
ALTER TABLE machines ADD COLUMN IF NOT EXISTS session_manager_id INT UNSIGNED DEFAULT NULL AFTER current_guest_id;
ALTER TABLE machines ADD COLUMN IF NOT EXISTS session_started_at DATETIME    DEFAULT NULL AFTER session_manager_id;
ALTER TABLE machines MODIFY COLUMN IF EXISTS plug_type ENUM('mystrom','shelly','none') NOT NULL DEFAULT 'none';

-- v2.11: session_started LogType für Aktivitätslog
ALTER TABLE activity_log MODIFY COLUMN type ENUM(
    'access_granted','access_denied','plug_on','plug_off',
    'guest_created','guest_deleted','machine_created','machine_deleted',
    'permission_granted','permission_revoked','login','guest_login','error','idle_off','session_started'
) NOT NULL;

-- ── v2.12: Maschinenpflege ────────────────────────────────────────────────────

-- Wartungsintervalle
CREATE TABLE IF NOT EXISTS maintenance_intervals (
    id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    machine_id       INT UNSIGNED NOT NULL,
    name             VARCHAR(200) NOT NULL,
    description      TEXT DEFAULT NULL,
    interval_hours   FLOAT        DEFAULT NULL,
    interval_days    INT          DEFAULT NULL,
    warning_hours    FLOAT        DEFAULT NULL,
    warning_days     INT          DEFAULT NULL,
    is_active        TINYINT(1)   NOT NULL DEFAULT 1,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Wartungsausführungen
CREATE TABLE IF NOT EXISTS maintenance_records (
    id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    interval_id         INT UNSIGNED NOT NULL,
    machine_id          INT UNSIGNED NOT NULL,
    performed_by        INT UNSIGNED DEFAULT NULL,
    performed_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    hours_at_execution  FLOAT        DEFAULT NULL,
    notes               TEXT         DEFAULT NULL,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (interval_id)  REFERENCES maintenance_intervals(id) ON DELETE CASCADE,
    FOREIGN KEY (machine_id)   REFERENCES machines(id)              ON DELETE CASCADE,
    FOREIGN KEY (performed_by) REFERENCES users(id)                 ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Kumulierte Betriebsstunden pro Maschine
ALTER TABLE machines ADD COLUMN IF NOT EXISTS total_hours FLOAT NOT NULL DEFAULT 0 AFTER session_started_at;

-- Neue LogTypes
ALTER TABLE activity_log MODIFY COLUMN type ENUM(
    'access_granted','access_denied','plug_on','plug_off',
    'guest_created','guest_deleted','machine_created','machine_deleted',
    'permission_granted','permission_revoked','login','guest_login',
    'error','idle_off','session_started','maintenance_due','maintenance_done'
) NOT NULL;

-- Login-Token für Lab Manager
ALTER TABLE users ADD COLUMN IF NOT EXISTS login_token VARCHAR(64) UNIQUE DEFAULT NULL;
