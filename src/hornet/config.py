"""Application settings, loaded from environment variables and .env.

Single source of truth for runtime configuration. Every other module
that needs configuration reads it via ``get_settings()`` — never from
os.environ directly, never from hardcoded constants.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Values are read from environment variables with the ``HORNET_``
    prefix, or from a ``.env`` file in the working directory. Unknown
    env vars are ignored so the presence of unrelated variables (PATH,
    HOME, etc.) never causes Settings to fail validation.
    """

    model_config = SettingsConfigDict(
        env_prefix="HORNET_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Database ----
    db_url: str = Field(
        default="postgresql+psycopg://hornet:hornet@localhost:5432/hornet",
        description="SQLAlchemy connection URL for the primary database.",
    )

    # ---- Environment ----
    env: Literal["development", "test", "production"] = Field(
        default="development",
        description="Deployment environment flag.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Minimum log level to emit.",
    )

    # ---- API server ----
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000, ge=1, le=65535)

    # ---- Source credentials ----
    # Read from HORNET_FRED_API_KEY. Wrapped in SecretStr so accidental
    # logging / repr of Settings never leaks the key. None means the
    # FRED adapter cannot be wired up in production — tests that never
    # hit real FRED can construct FredAdapter directly with a literal
    # api_key and bypass Settings entirely.
    fred_api_key: SecretStr | None = Field(
        default=None,
        description="API key for FRED (https://fred.stlouisfed.org). Required for live ingest.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a memoized Settings instance.

    Memoized because reading env vars and .env is cheap-but-not-free
    and Settings shouldn't change mid-process. Tests that need fresh
    settings can call ``get_settings.cache_clear()``.
    """
    return Settings()
