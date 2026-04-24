"""Tests for AlertConfig and YAML seed loading."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ridge.alerts.config import AlertConfig
from ridge.seeds.loader import load_alert_config_from_yaml


class TestAlertConfig:
    def test_defaults_match_v1(self) -> None:
        """Verify default thresholds match v1 settings."""
        config = AlertConfig()
        assert config.watch_threshold == 1.0
        assert config.alert_threshold == 1.5
        assert config.escalate_threshold == 2.0
        assert config.min_coverage_for_escalate == 0.5
        assert config.streak_required == 2
        assert config.velocity_threshold == 0.5
        assert config.max_daily_escalations == 10

    def test_threshold_order_enforced(self) -> None:
        """Thresholds must be strictly ordered."""
        with pytest.raises(ValueError, match="strictly ordered"):
            AlertConfig(
                watch_threshold=2.0,
                alert_threshold=1.5,
                escalate_threshold=1.0,
            )

    def test_frozen(self) -> None:
        """Config should be immutable."""
        config = AlertConfig()
        with pytest.raises(ValidationError):
            config.watch_threshold = 0.5  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            AlertConfig(bogus_field=42)  # type: ignore[call-arg]


class TestAlertConfigYamlSeed:
    def test_loads_default_seed(self) -> None:
        """Packaged alert_config.yaml should load successfully."""
        config = load_alert_config_from_yaml()
        assert config.watch_threshold == 1.0
        assert config.escalate_threshold == 2.0

    def test_loads_custom_yaml(self) -> None:
        yaml_text = """
alert_config:
  watch_threshold: 0.8
  alert_threshold: 1.2
  escalate_threshold: 1.8
  min_coverage_for_escalate: 0.75
  streak_required: 3
  velocity_threshold: 0.4
  max_daily_escalations: 5
"""
        config = load_alert_config_from_yaml(yaml_text)
        assert config.watch_threshold == 0.8
        assert config.streak_required == 3
        assert config.max_daily_escalations == 5

    def test_rejects_bad_yaml(self) -> None:
        with pytest.raises(ValueError, match="top-level"):
            load_alert_config_from_yaml("not_a_mapping: [1,2,3]")

    def test_rejects_missing_key(self) -> None:
        with pytest.raises(ValueError, match="alert_config"):
            load_alert_config_from_yaml("wrong_key: {}")
