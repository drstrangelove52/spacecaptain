"""
Schema-Migrationen — idempotent, laufen bei jedem Backend-Start.
Nur ADD COLUMN / CREATE TABLE IF NOT EXISTS — nie destruktiv.
"""
import logging
import secrets
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger(__name__)


async def run_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:

        # ── v1.21: Plug-Pool ──────────────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS plugs (
                id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                plug_type VARCHAR(20) NOT NULL,
                plug_ip VARCHAR(50) NOT NULL,
                plug_token VARCHAR(255) DEFAULT NULL,
                plug_poll_interval_sec INT UNSIGNED DEFAULT 60,
                notes TEXT DEFAULT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        await _add_column_if_missing(conn, "machines", "plug_id",
                                     "INT UNSIGNED DEFAULT NULL")
        # plug_poll_interval_sec: add if missing; also fix NOT NULL w/o DEFAULT
        # (SQLAlchemy create_all creates columns without server-side DEFAULT)
        await _add_column_if_missing(conn, "plugs", "plug_poll_interval_sec",
                                     "INT UNSIGNED DEFAULT 60")
        _fix_res = await conn.execute(text(
            "SELECT COLUMN_DEFAULT FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='plugs' "
            "AND COLUMN_NAME='plug_poll_interval_sec'"
        ))
        _fix_row = _fix_res.fetchone()
        if _fix_row and _fix_row[0] is None:
            await conn.execute(text(
                "ALTER TABLE plugs MODIFY COLUMN plug_poll_interval_sec INT UNSIGNED NULL DEFAULT 60"
            ))
            log.info("Migration: plugs.plug_poll_interval_sec DEFAULT 60 gesetzt")

        # ── v1.20: Sicherheitshinweise pro Maschine ───────────────────────────
        await _add_column_if_missing(conn, "machines", "safety_notes",
                                     "TEXT DEFAULT NULL")

        # ── v2.12: total_hours auf machines ──────────────────────────────────
        await _add_column_if_missing(conn, "machines", "total_hours",
                                     "FLOAT NOT NULL DEFAULT 0 AFTER session_started_at")

        # ── v2.12: maintenance_intervals ─────────────────────────────────────
        await conn.execute(text("""
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
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        # ── v2.12: maintenance_records ────────────────────────────────────────
        await conn.execute(text("""
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
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        # ── v2.12: neue LogTypes in ENUM ─────────────────────────────────────
        await _extend_enum_if_needed(conn, "activity_log", "type", [
            "maintenance_due", "maintenance_done"
        ])

    # ── v1.01: name in maintenance_records speichern ─────────────────────────
        await _add_column_if_missing(conn, "maintenance_records", "name",
                                     "VARCHAR(200) DEFAULT NULL AFTER interval_id")

    # ── v2.17: login_token für Gäste ─────────────────────────────────────────
        await _add_column_if_missing(conn, "guests", "login_token",
                                     "VARCHAR(64) DEFAULT NULL UNIQUE")

    # ── v1.04: manager_id auf machine_sessions ───────────────────────────────
        await _add_column_if_missing(conn, "machine_sessions", "manager_id",
                                     "INT UNSIGNED DEFAULT NULL")

    # ── v1.04: training_required auf machines ────────────────────────────────
        await _add_column_if_missing(conn, "machines", "training_required",
                                     "TINYINT(1) NOT NULL DEFAULT 1")

    # ── v1.04: is_blocked auf permissions ────────────────────────────────────
        await _add_column_if_missing(conn, "permissions", "is_blocked",
                                     "TINYINT(1) NOT NULL DEFAULT 0")

    # ── v2.16: interval_id in maintenance_records optional ───────────────────
        await conn.execute(text(
            "ALTER TABLE maintenance_records MODIFY COLUMN interval_id INT UNSIGNED DEFAULT NULL"
        ))

        # ── v1.03: system_settings ────────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS system_settings (
                id                  INT UNSIGNED PRIMARY KEY DEFAULT 1,
                nfc_writer_url      VARCHAR(255) NOT NULL DEFAULT '',
                jwt_expire_minutes  INT NOT NULL DEFAULT 480,
                guest_token_days    INT NOT NULL DEFAULT 365
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        await _add_column_if_missing(conn, "system_settings", "modal_backdrop_input",
                                     "TINYINT(1) NOT NULL DEFAULT 1")
        await _add_column_if_missing(conn, "system_settings", "modal_backdrop_display",
                                     "TINYINT(1) NOT NULL DEFAULT 1")
        from app.config import get_settings as _get_settings
        _env = _get_settings()
        await conn.execute(text(
            "INSERT IGNORE INTO system_settings (id, nfc_writer_url, jwt_expire_minutes, guest_token_days) "
            "VALUES (1, :url, :jwt, 365)"
        ).bindparams(url=_env.nfc_writer_url, jwt=_env.jwt_expire_minutes))

        # ── v1.06: queue_reservation_minutes in system_settings ──────────────
        await _add_column_if_missing(conn, "system_settings", "queue_reservation_minutes",
                                     "INT NOT NULL DEFAULT 5")
        await _add_column_if_missing(conn, "system_settings", "display_refresh_seconds",
                                     "INT NOT NULL DEFAULT 30")

        # ── v1.06: machine_queue ──────────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS machine_queue (
                id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                machine_id   INT UNSIGNED NOT NULL,
                guest_id     INT UNSIGNED NOT NULL,
                status       ENUM('waiting','notified','done','expired') NOT NULL DEFAULT 'waiting',
                joined_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                notified_at  DATETIME DEFAULT NULL,
                expires_at   DATETIME DEFAULT NULL,
                UNIQUE KEY uq_machine_guest (machine_id, guest_id),
                FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE,
                FOREIGN KEY (guest_id)   REFERENCES guests(id)   ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        # ── v1.08: dashboard_refresh_seconds in system_settings ──────────────
        await _add_column_if_missing(conn, "system_settings", "dashboard_refresh_seconds",
                                     "INT NOT NULL DEFAULT 30")
        await _add_column_if_missing(conn, "system_settings", "display_page_size",
                                     "INT NOT NULL DEFAULT 8")

        # ── v1.09: pending_approval für Gast-Selbstregistrierung ─────────────
        await _add_column_if_missing(conn, "guests", "pending_approval",
                                     "TINYINT(1) NOT NULL DEFAULT 0")
        await _extend_enum_if_needed(conn, "activity_log", "type", [
            "guest_registered", "guest_approved"
        ])

        # ── v1.07: ticker_text + announcement in system_settings ─────────────
        await _add_column_if_missing(conn, "system_settings", "ticker_text",
                                     "TEXT DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "ticker_speed",
                                     "INT NOT NULL DEFAULT 80")
        await _add_column_if_missing(conn, "system_settings", "ticker_font_size",
                                     "INT NOT NULL DEFAULT 18")
        await _add_column_if_missing(conn, "system_settings", "announcement",
                                     "TEXT DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "announcement_font_size",
                                     "INT NOT NULL DEFAULT 20")

        # ── v1.06: push_subscriptions ─────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                guest_id    INT UNSIGNED NOT NULL,
                endpoint    VARCHAR(500) NOT NULL,
                p256dh      VARCHAR(255) NOT NULL,
                auth        VARCHAR(64)  NOT NULL,
                created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_guest_endpoint (guest_id, endpoint(200)),
                FOREIGN KEY (guest_id) REFERENCES guests(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        # ── v1.09: announcements ──────────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS announcements (
                id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                text              TEXT NOT NULL,
                is_active         TINYINT(1) NOT NULL DEFAULT 1,
                is_recurring      TINYINT(1) NOT NULL DEFAULT 0,
                display_type      VARCHAR(20) NOT NULL DEFAULT 'banner',
                start_at          DATETIME DEFAULT NULL,
                end_at            DATETIME DEFAULT NULL,
                recur_days        VARCHAR(20) DEFAULT NULL,
                recur_start_time  TIME DEFAULT NULL,
                recur_end_time    TIME DEFAULT NULL,
                recur_valid_from  DATE DEFAULT NULL,
                recur_valid_until DATE DEFAULT NULL,
                created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        await _add_column_if_missing(conn, "announcements", "display_type",
                                     "VARCHAR(20) NOT NULL DEFAULT 'banner'")

        # ── v1.10: agb_text in system_settings ───────────────────────────────
        await _add_column_if_missing(conn, "system_settings", "agb_text",
                                     "TEXT DEFAULT NULL")

        # ── v1.11: ntfy + emergency ───────────────────────────────────────────
        await _extend_enum_if_needed(conn, "activity_log", "type", [
            "emergency_triggered", "emergency_cancelled"
        ])
        await _add_column_if_missing(conn, "system_settings", "ntfy_server",
                                     "VARCHAR(255) NOT NULL DEFAULT 'https://ntfy.sh'")
        await _add_column_if_missing(conn, "system_settings", "ntfy_token",
                                     "VARCHAR(255) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "emergency_trigger_token",
                                     "VARCHAR(100) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "emergency_text",
                                     "TEXT DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "emergency_ntfy_message",
                                     "TEXT DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "emergency_duration_min",
                                     "INT NOT NULL DEFAULT 0")
        # emergency_duration_min umbenannt zu emergency_duration_sec (v1.12)
        await _add_column_if_missing(conn, "system_settings", "emergency_duration_sec",
                                     "INT NOT NULL DEFAULT 0")
        await _add_column_if_missing(conn, "system_settings", "emergency_ntfy_topic_id",
                                     "INT DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "emergency_plug_ip",
                                     "VARCHAR(100) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "emergency_plug_type",
                                     "VARCHAR(20) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "emergency_plug_token",
                                     "VARCHAR(200) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "emergency_plug2_ip",
                                     "VARCHAR(100) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "emergency_plug2_type",
                                     "VARCHAR(20) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "emergency_plug2_token",
                                     "VARCHAR(200) DEFAULT NULL")

        # ── v1.13: ntfy_topic pro Gast ────────────────────────────────────────
        await _add_column_if_missing(conn, "guests", "ntfy_topic",
                                     "VARCHAR(80) DEFAULT NULL")
        # Bestehende Gäste ohne Topic nachträglich befüllen (einmalig)
        await _backfill_guest_ntfy_topics(conn)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ntfy_topics (
                id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                `key`       VARCHAR(50)  NOT NULL UNIQUE,
                topic       VARCHAR(200) NOT NULL,
                title       VARCHAR(200) NOT NULL,
                description TEXT         DEFAULT NULL,
                created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS emergency_state (
                id           INT UNSIGNED PRIMARY KEY DEFAULT 1,
                active       TINYINT(1)   NOT NULL DEFAULT 0,
                triggered_at DATETIME     DEFAULT NULL,
                triggered_by VARCHAR(100) DEFAULT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        await conn.execute(text(
            "INSERT IGNORE INTO emergency_state (id, active) VALUES (1, 0)"
        ))

        # ── v1.14: auto_backup ────────────────────────────────────────────────
        await _add_column_if_missing(conn, "system_settings", "auto_backup_enabled",
                                     "TINYINT(1) NOT NULL DEFAULT 0")
        await _add_column_if_missing(conn, "system_settings", "auto_backup_hour",
                                     "INT NOT NULL DEFAULT 3")
        await _add_column_if_missing(conn, "system_settings", "auto_backup_minute",
                                     "INT NOT NULL DEFAULT 0")
        await _add_column_if_missing(conn, "system_settings", "auto_backup_keep",
                                     "INT NOT NULL DEFAULT 30")

        # ── v1.15: Shelly Gen2/Gen3/Gen4 ─────────────────────────────────────
        await _extend_enum_if_needed(conn, "machines", "plug_type", ["shelly_gen2"])

        # ── v1.17: Seriennummer auf machines ─────────────────────────────────
        await _add_column_if_missing(conn, "machines", "serial_number",
                                     "VARCHAR(100) DEFAULT NULL")

        # ── v1.18: Aktivitätslog für Update-Aktionen ─────────────────────────
        await _extend_enum_if_needed(conn, "activity_log", "type", [
            "user_created", "user_updated", "guest_updated", "machine_updated",
        ])

        # ── v1.24: Aktivitätslog für Automationen ────────────────────────────
        await _extend_enum_if_needed(conn, "activity_log", "type", [
            "automation_created", "automation_updated", "automation_deleted",
        ])

        # ── v1.16: Aktivitätslog für alle fehlenden Aktionen ─────────────────
        await _extend_enum_if_needed(conn, "activity_log", "type", [
            "settings_changed",
            "announcement_created", "announcement_updated", "announcement_deleted",
            "ntfy_topic_created", "ntfy_topic_updated", "ntfy_topic_deleted",
            "queue_joined", "queue_left", "queue_notified",
            "backup_exported", "backup_imported",
        ])

        # ── v1.19: Makerspace-Name ────────────────────────────────────────────────
        await _add_column_if_missing(conn, "system_settings", "space_name",
                                     "VARCHAR(100) NOT NULL DEFAULT ''")

        # ── v1.17: Maschinenkategorien ────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS machine_categories (
                id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                name        VARCHAR(50)  NOT NULL UNIQUE,
                icon        VARCHAR(10)  NOT NULL DEFAULT '🔧',
                sort_order  INT          NOT NULL DEFAULT 0,
                created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        # Standardkategorien eintragen — nur wenn Tabelle noch leer
        result = await conn.execute(text("SELECT COUNT(*) FROM machine_categories"))
        if result.scalar() == 0:
            await conn.execute(text("""
                INSERT INTO machine_categories (name, icon, sort_order, created_at) VALUES
                ('Laser',      '⚡', 1, NOW()),
                ('CNC',        '⚙', 2, NOW()),
                ('3D-Druck',   '🖨', 3, NOW()),
                ('Holz',       '🪚', 4, NOW()),
                ('Metall',     '🔩', 5, NOW()),
                ('Elektronik', '🔌', 6, NOW()),
                ('Textil',     '🧵', 7, NOW()),
                ('Sonstiges',  '🔧', 8, NOW())
            """))

        # ── v1.25: session_source auf machine_sessions ───────────────────────
        await _add_column_if_missing(conn, "machine_sessions", "session_source",
                                     "VARCHAR(50) DEFAULT NULL")

        # ── v1.24: machine_automations (Leistungs-Automation) ────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS machine_automations (
                id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                source_machine_id   INT UNSIGNED NOT NULL,
                target_machine_id   INT UNSIGNED NOT NULL,
                on_threshold_w      FLOAT NOT NULL,
                off_threshold_w     FLOAT NOT NULL,
                off_delay_sec       INT NOT NULL DEFAULT 30,
                enabled             TINYINT(1) NOT NULL DEFAULT 1,
                created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_machine_id) REFERENCES machines(id) ON DELETE CASCADE,
                FOREIGN KEY (target_machine_id) REFERENCES machines(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        # ── v1.23: machine_plugs (mehrere Plugs pro Maschine) ────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS machine_plugs (
                id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                machine_id  INT UNSIGNED NOT NULL,
                plug_id     INT NOT NULL,
                sort_order  INT NOT NULL DEFAULT 0,
                UNIQUE KEY uq_machine_plug (machine_id, plug_id),
                FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE,
                FOREIGN KEY (plug_id)    REFERENCES plugs(id)    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        # Bestehende Zuweisungen aus machines.plug_id übernehmen (einmalig, idempotent)
        await conn.execute(text("""
            INSERT IGNORE INTO machine_plugs (machine_id, plug_id, sort_order)
            SELECT id, plug_id, 0 FROM machines WHERE plug_id IS NOT NULL
        """))

        # ── v1.26: Raum-Öffnungsstatus + Zeitpläne ───────────────────────────
        await _add_column_if_missing(conn, "system_settings", "room_open",
                                     "TINYINT(1) NOT NULL DEFAULT 0")
        await _add_column_if_missing(conn, "system_settings", "room_open_since",
                                     "DATETIME DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "room_open_auto",
                                     "TINYINT(1) NOT NULL DEFAULT 1")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS device_schedules (
                id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                machine_id        INT UNSIGNED NOT NULL,
                name              VARCHAR(100) NOT NULL DEFAULT '',
                days              VARCHAR(20)  NOT NULL,
                time_on           TIME         NOT NULL,
                time_off          TIME         NOT NULL,
                require_room_open TINYINT(1)   NOT NULL DEFAULT 1,
                enabled           TINYINT(1)   NOT NULL DEFAULT 1,
                created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        await _extend_enum_if_needed(conn, "activity_log", "type", [
            "schedule_created", "schedule_updated", "schedule_deleted",
            "schedule_on", "schedule_off", "room_opened", "room_closed",
        ])

        # ── v1.27: Kombiniertes Regelwerk (automation_rules + rule_conditions) ─
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS automation_rules (
                id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                name              VARCHAR(100) NOT NULL DEFAULT '',
                target_machine_id INT UNSIGNED NOT NULL,
                off_delay_sec     INT NOT NULL DEFAULT 0,
                enabled           TINYINT(1) NOT NULL DEFAULT 1,
                created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (target_machine_id) REFERENCES machines(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rule_conditions (
                id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                rule_id           INT UNSIGNED NOT NULL,
                type              VARCHAR(30) NOT NULL,
                source_machine_id INT UNSIGNED NULL,
                power_on_w        FLOAT NULL,
                power_off_w       FLOAT NULL,
                days              VARCHAR(20) NULL,
                time_on           TIME NULL,
                time_off          TIME NULL,
                FOREIGN KEY (rule_id) REFERENCES automation_rules(id) ON DELETE CASCADE,
                FOREIGN KEY (source_machine_id) REFERENCES machines(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        # Bestehende machine_automations migrieren (einmalig)
        await _migrate_automations_to_rules(conn)
        # Bestehende device_schedules migrieren (einmalig)
        await _migrate_schedules_to_rules(conn)
        await _extend_enum_if_needed(conn, "activity_log", "type", [
            "rule_created", "rule_updated", "rule_deleted", "rule_on", "rule_off",
        ])

        # ── v1.28: ntfy_topics.key nullable (Feld wird nicht mehr benötigt) ───
        await conn.execute(text(
            "ALTER TABLE ntfy_topics MODIFY COLUMN `key` VARCHAR(50) DEFAULT NULL"
        ))

        # ── v1.29: force_off_on_close + action_type ──────────────────────────
        await _add_column_if_missing(conn, "machines", "force_off_on_close",
                                     "TINYINT(1) NOT NULL DEFAULT 0")
        await _add_column_if_missing(conn, "automation_rules", "action_type",
                                     "VARCHAR(20) NOT NULL DEFAULT 'machine'")
        # target_machine_id nullable machen (für room_open/room_close Regeln)
        await conn.execute(text(
            "ALTER TABLE automation_rules MODIFY COLUMN target_machine_id INT UNSIGNED DEFAULT NULL"
        ))
        await _extend_enum_if_needed(conn, "activity_log", "type", [
            "room_access_denied",
        ])

        # ── v1.30: notify-Aktion für automation_rules ─────────────────────────
        await _add_column_if_missing(conn, "automation_rules", "notify_topic_id",
                                     "INT DEFAULT NULL")
        await _add_column_if_missing(conn, "automation_rules", "notify_message",
                                     "TEXT DEFAULT NULL")
        await _extend_enum_if_needed(conn, "activity_log", "type", [
            "rule_notify",
        ])

        # ── v1.31: Standortverwaltung ──────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS machine_locations (
                id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                name        VARCHAR(100) NOT NULL UNIQUE,
                sort_order  INT          NOT NULL DEFAULT 0,
                created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        # ── v1.32: Notfall-Plugs über Plug-Pool ───────────────────────────────
        await _add_column_if_missing(conn, "system_settings", "emergency_plug_id",
                                     "INT UNSIGNED DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "emergency_plug2_id",
                                     "INT UNSIGNED DEFAULT NULL")

        # ── v1.33: LogType.system ─────────────────────────────────────────────
        await _extend_enum_if_needed(conn, "activity_log", "type", ["system"])

        # ── v1.34: Power-Manager Rolle ────────────────────────────────────────
        await _extend_enum_if_needed(conn, "users", "role", ["power_manager"])

        # ── v1.35: Gäste-Session Gültigkeit ──────────────────────────────────
        await _add_column_if_missing(conn, "system_settings", "guest_token_ttl_hours",
                                     "INT NOT NULL DEFAULT 8")

        # ── v1.36: Tailscale Fernzugriff ──────────────────────────────────────
        await _add_column_if_missing(conn, "system_settings", "ts_enabled",
                                     "BOOLEAN NOT NULL DEFAULT FALSE")
        await _add_column_if_missing(conn, "system_settings", "ts_authkey",
                                     "VARCHAR(255) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "ts_hostname",
                                     "VARCHAR(100) NOT NULL DEFAULT 'spacecaptain'")

        # ── v1.37: MCP-Server ─────────────────────────────────────────────────
        await _add_column_if_missing(conn, "system_settings", "mcp_enabled",
                                     "BOOLEAN NOT NULL DEFAULT FALSE")
        await _add_column_if_missing(conn, "system_settings", "mcp_api_token",
                                     "VARCHAR(64) DEFAULT NULL")
        # ── v1.38: MCP-Benutzer ───────────────────────────────────────────────
        await _add_column_if_missing(conn, "system_settings", "mcp_user_id",
                                     "INT NULL DEFAULT NULL")

        # Token beim ersten Start automatisch generieren
        res = await conn.execute(text(
            "SELECT mcp_api_token FROM system_settings WHERE id = 1"
        ))
        row = res.fetchone()
        if row and row[0] is None:
            token = secrets.token_urlsafe(32)
            await conn.execute(text(
                "UPDATE system_settings SET mcp_api_token = :t WHERE id = 1"
            ), {"t": token})
            log.info("Migration: mcp_api_token generiert")

        # ── v1.39: Inventar-Erweiterung (Kaufdatum, Neuwert, Eigentümer) + Akku-Management ──
        await _add_column_if_missing(conn, "machines", "purchase_date", "DATE DEFAULT NULL")
        await _add_column_if_missing(conn, "machines", "value_new", "FLOAT DEFAULT NULL")
        await _add_column_if_missing(conn, "machines", "owner_id", "INT DEFAULT NULL")

        # ── v1.40: Konfigurierbare Währung ─────────────────────────────────
        await _add_column_if_missing(conn, "system_settings", "currency", "VARCHAR(10) NOT NULL DEFAULT 'CHF'")

        # ── v1.41: Akku-Feld vereinheitlicht (Neuwert statt Neupreis) ──────
        await _rename_column_if_needed(conn, "batteries", "price_new", "value_new", "FLOAT DEFAULT NULL")

        # ── v1.42: Externes SFTP-Backup (Passwort- oder Key-Auth) ──────────
        await _add_column_if_missing(conn, "system_settings", "backup_remote_enabled", "TINYINT(1) NOT NULL DEFAULT 0")
        await _add_column_if_missing(conn, "system_settings", "backup_remote_host", "VARCHAR(255) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "backup_remote_port", "INT NOT NULL DEFAULT 22")
        await _add_column_if_missing(conn, "system_settings", "backup_remote_username", "VARCHAR(100) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "backup_remote_path", "VARCHAR(500) NOT NULL DEFAULT '/'")
        await _add_column_if_missing(conn, "system_settings", "backup_remote_auth_type", "VARCHAR(20) NOT NULL DEFAULT 'password'")
        await _add_column_if_missing(conn, "system_settings", "backup_remote_password", "VARCHAR(255) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "backup_remote_private_key", "TEXT DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "backup_remote_key_passphrase", "VARCHAR(255) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "backup_remote_last_status", "VARCHAR(20) DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "backup_remote_last_message", "TEXT DEFAULT NULL")
        await _add_column_if_missing(conn, "system_settings", "backup_remote_last_at", "DATETIME DEFAULT NULL")

        # ── v1.43: Akku-Identifikation (Name/Nummer, Seriennummer, Bemerkung) ──
        await _add_column_if_missing(conn, "batteries", "name", "VARCHAR(100) DEFAULT NULL")
        await _add_column_if_missing(conn, "batteries", "serial_number", "VARCHAR(100) DEFAULT NULL")
        await _add_column_if_missing(conn, "batteries", "comment", "TEXT DEFAULT NULL")

        # ── v1.44: Dokumentations-Link pro Maschine ────────────────────────
        await _add_column_if_missing(conn, "machines", "doc_url", "VARCHAR(500) DEFAULT NULL")

    log.info("Migrationen abgeschlossen")


async def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    """Fügt eine Spalte hinzu — nur wenn sie noch nicht existiert."""
    result = await conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    if result.scalar() == 0:
        await conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}"))
        log.info(f"Migration: {table}.{column} hinzugefügt")


async def _rename_column_if_needed(conn, table: str, old_column: str, new_column: str, definition: str) -> None:
    """Benennt eine Spalte um — nur wenn die alte existiert und die neue noch nicht."""
    result = await conn.execute(text(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table "
        "AND COLUMN_NAME IN (:old_column, :new_column)"
    ), {"table": table, "old_column": old_column, "new_column": new_column})
    existing = {row[0] for row in result.fetchall()}
    if old_column in existing and new_column not in existing:
        await conn.execute(text(
            f"ALTER TABLE `{table}` CHANGE COLUMN `{old_column}` `{new_column}` {definition}"
        ))
        log.info(f"Migration: {table}.{old_column} → {new_column} umbenannt")


async def _extend_enum_if_needed(conn, table: str, column: str, new_values: list[str]) -> None:
    """Erweitert einen ENUM um fehlende Werte."""
    result = await conn.execute(text(
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    row = result.fetchone()
    if not row:
        return
    current_type = row[0]  # z.B. "enum('a','b','c')"

    missing = [v for v in new_values if f"'{v}'" not in current_type]
    if not missing:
        return

    # Alle aktuellen Werte + neue zusammenstellen
    import re
    existing = re.findall(r"'([^']+)'", current_type)
    all_values = existing + [v for v in new_values if v not in existing]
    enum_def = "ENUM(" + ",".join(f"'{v}'" for v in all_values) + ") NOT NULL"
    await conn.execute(text(f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` {enum_def}"))
    log.info(f"Migration: {table}.{column} ENUM erweitert um {missing}")


async def _backfill_guest_ntfy_topics(conn) -> None:
    """Generiert ntfy-Topics für bestehende Gäste ohne Topic (einmalig, idempotent)."""
    result = await conn.execute(text("SELECT id FROM guests WHERE ntfy_topic IS NULL"))
    rows = result.fetchall()
    if not rows:
        return
    for (guest_id,) in rows:
        topic = f"sc-{secrets.token_urlsafe(12)}"
        await conn.execute(text(
            "UPDATE guests SET ntfy_topic = :topic WHERE id = :id AND ntfy_topic IS NULL"
        ), {"topic": topic, "id": guest_id})
    log.info(f"Migration: ntfy_topic für {len(rows)} bestehende Gäste nachgefüllt")


async def _migrate_automations_to_rules(conn) -> None:
    """Migriert machine_automations → automation_rules + rule_conditions (einmalig)."""
    # Prüfen ob bereits Regeln vorhanden (dann schon migriert)
    existing = await conn.execute(text("SELECT COUNT(*) FROM automation_rules"))
    if existing.scalar() > 0:
        return
    old = await conn.execute(text("SELECT * FROM machine_automations"))
    rows = old.fetchall()
    if not rows:
        return
    for row in rows:
        r = await conn.execute(text("""
            INSERT INTO automation_rules (name, target_machine_id, off_delay_sec, enabled, created_at)
            VALUES (:name, :tid, :delay, :enabled, :created)
        """), {
            "name": f"Automation {row[0]}",
            "tid": row[2],   # target_machine_id
            "delay": row[5], # off_delay_sec
            "enabled": row[6],
            "created": row[7],
        })
        rule_id = r.lastrowid
        await conn.execute(text("""
            INSERT INTO rule_conditions (rule_id, type, source_machine_id, power_on_w, power_off_w)
            VALUES (:rule_id, 'power', :src, :on_w, :off_w)
        """), {
            "rule_id": rule_id,
            "src": row[1],   # source_machine_id
            "on_w": row[3],  # on_threshold_w
            "off_w": row[4], # off_threshold_w
        })
    log.info(f"Migration: {len(rows)} machine_automations → automation_rules migriert")


async def _migrate_schedules_to_rules(conn) -> None:
    """Migriert device_schedules → automation_rules + rule_conditions (einmalig, nur wenn automation_rules leer war)."""
    old = await conn.execute(text("SELECT * FROM device_schedules"))
    rows = old.fetchall()
    if not rows:
        return
    for row in rows:
        # Prüfen ob diese Regel schon existiert (per Name-Match)
        name = f"Zeitplan: {row[1]}" if row[2] else f"Zeitplan {row[0]}"
        ex = await conn.execute(text(
            "SELECT COUNT(*) FROM automation_rules WHERE name = :name"
        ), {"name": name})
        if ex.scalar() > 0:
            continue
        r = await conn.execute(text("""
            INSERT INTO automation_rules (name, target_machine_id, off_delay_sec, enabled, created_at)
            VALUES (:name, :tid, 0, :enabled, :created)
        """), {
            "name": name,
            "tid": row[1],   # machine_id
            "enabled": row[5],
            "created": row[7],
        })
        rule_id = r.lastrowid
        # Schedule-Bedingung
        await conn.execute(text("""
            INSERT INTO rule_conditions (rule_id, type, days, time_on, time_off)
            VALUES (:rule_id, 'schedule', :days, :on, :off)
        """), {"rule_id": rule_id, "days": row[3], "on": row[4], "off": row[5]})
        # Raum-Bedingung wenn gesetzt
        if row[6]:  # require_room_open
            await conn.execute(text("""
                INSERT INTO rule_conditions (rule_id, type) VALUES (:rule_id, 'room_open')
            """), {"rule_id": rule_id})
    log.info(f"Migration: {len(rows)} device_schedules → automation_rules migriert")
