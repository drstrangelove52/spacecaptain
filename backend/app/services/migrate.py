"""
Schema-Migrationen — idempotent, laufen bei jedem Backend-Start.
Nur ADD COLUMN / CREATE TABLE IF NOT EXISTS — nie destruktiv.
"""
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger(__name__)


async def run_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:

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

    log.info("Migrationen abgeschlossen")


async def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    """Fügt eine Spalte hinzu — nur wenn sie noch nicht existiert."""
    result = await conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        f"AND TABLE_NAME = '{table}' AND COLUMN_NAME = '{column}'"
    ))
    if result.scalar() == 0:
        await conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}"))
        log.info(f"Migration: {table}.{column} hinzugefügt")


async def _extend_enum_if_needed(conn, table: str, column: str, new_values: list[str]) -> None:
    """Erweitert einen ENUM um fehlende Werte."""
    result = await conn.execute(text(
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        f"AND TABLE_NAME = '{table}' AND COLUMN_NAME = '{column}'"
    ))
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
