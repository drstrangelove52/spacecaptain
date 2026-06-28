from pydantic_settings import BaseSettings
from functools import lru_cache
from urllib.parse import quote_plus


class Settings(BaseSettings):
    # Datenbank
    db_host: str = "db"
    db_port: int = 3306
    db_name: str = "spacecaptain"
    db_user: str = "spacecaptain"
    db_password: str = "changeme"

    # JWT
    jwt_secret: str = "changeme"
    jwt_expire_minutes: int = 480  # 8 Stunden — typische Arbeitsschicht
    jwt_algorithm: str = "HS256"

    # CORS
    allowed_origins: str = "http://localhost"

    # NFC-Schreibgerät (ESP32)
    nfc_writer_url: str = ""  # z.B. http://nfc-writer.local oder http://192.168.1.50 — leer = deaktiviert

    # MCP-Server (interner Service-Key, nie nach aussen exponiert)
    mcp_backend_key: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"mysql+aiomysql://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            f"?charset=utf8mb4"
        )

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    class Config:
        env_file = ".env"


_WEAK_SECRETS = {"changeme", "secret", "password", "12345678", ""}

def _validate_secrets(s: Settings) -> None:
    errors = []
    if s.jwt_secret in _WEAK_SECRETS or len(s.jwt_secret) < 32:
        errors.append("JWT_SECRET muss mindestens 32 Zeichen lang sein und darf nicht 'changeme' sein")
    if s.db_password in _WEAK_SECRETS:
        errors.append("DB_PASSWORD darf nicht 'changeme' oder leer sein")
    if errors:
        raise RuntimeError(
            "Unsichere Konfiguration — Server startet nicht:\n" + "\n".join(f"  - {e}" for e in errors)
        )

@lru_cache
def get_settings() -> Settings:
    s = Settings()
    import os
    if os.environ.get("SPACECAPTAIN_SKIP_SECRET_CHECK") != "1":
        _validate_secrets(s)
    return s


APP_VERSION = "1.33"

import os as _os, zoneinfo as _zi

def _read_build_nr() -> str:
    try:
        with open("/app/update_trigger/build_nr") as _f:
            v = _f.read().strip()
            if v:
                return v
    except OSError:
        pass
    return _os.environ.get("BUILD_NR", "")

BUILD_NR = _read_build_nr()

# Patch: Zeitzone aus Umgebungsvariable lesen (wird in docker-compose gesetzt)
_tz_name = _os.environ.get("TZ", "UTC")
try:
    APP_TIMEZONE = _zi.ZoneInfo(_tz_name)
except Exception:
    APP_TIMEZONE = _zi.ZoneInfo("UTC")
