"""Tests for the Settings class and get_settings() memoization."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hornet.config import Settings, get_settings


class TestSettings:
    def test_settings_constructs(self) -> None:
        """Settings should load whether or not .env is present."""
        settings = Settings()
        assert isinstance(settings.db_url, str)
        assert settings.env in ("development", "test", "production")
        assert settings.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")
        assert 1 <= settings.api_port <= 65535

    def test_db_url_points_at_postgres(self) -> None:
        settings = Settings()
        assert "postgresql" in settings.db_url

    def test_rejects_invalid_env(self) -> None:
        with pytest.raises(ValidationError):
            Settings(env="staging")

    def test_rejects_invalid_log_level(self) -> None:
        with pytest.raises(ValidationError):
            Settings(log_level="CHATTY")

    def test_rejects_out_of_range_port(self) -> None:
        with pytest.raises(ValidationError):
            Settings(api_port=99999)

    def test_env_var_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HORNET_LOG_LEVEL", "DEBUG")
        get_settings.cache_clear()
        try:
            settings = get_settings()
            assert settings.log_level == "DEBUG"
        finally:
            get_settings.cache_clear()

    def test_get_settings_memoizes(self) -> None:
        get_settings.cache_clear()
        try:
            s1 = get_settings()
            s2 = get_settings()
            assert s1 is s2
        finally:
            get_settings.cache_clear()
