from pydantic_settings import BaseSettings
from functools import lru_cache


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
    nfc_writer_url: str = ""  # z.B. http://10.10.1.59 — leer = deaktiviert

    @property
    def database_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            f"?charset=utf8mb4"
        )

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


APP_VERSION = "1.03"

# Patch: Zeitzone aus Umgebungsvariable lesen (wird in docker-compose gesetzt)
import os as _os, zoneinfo as _zi
_tz_name = _os.environ.get("TZ", "UTC")
try:
    APP_TIMEZONE = _zi.ZoneInfo(_tz_name)
except Exception:
    APP_TIMEZONE = _zi.ZoneInfo("UTC")
