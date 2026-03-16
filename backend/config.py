"""
Application configuration using pydantic-settings.
Loads from .env file or environment variables.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Modbus
    MODBUS_MODE: str = "tcp"  # tcp | rtu
    MODBUS_TCP_HOST: str = "127.0.0.1"
    MODBUS_TCP_PORT: int = 502
    MODBUS_RTU_PORT: str = "COM3"
    MODBUS_BAUDRATE: int = 9600
    MODBUS_TIMEOUT: int = 3

    # Register map
    REGISTER_MAP_FILE: str = "register_maps/chiller_default.yaml"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./chiller.db"

    # Security
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # CORS
    ALLOWED_ORIGINS: list[str] = ["*"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
