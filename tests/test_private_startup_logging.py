"""Regression tests for private startup diagnostics with synthetic identities."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from addon.src.main import create_config, log_startup_summary

SYNTHETIC_EMAIL = "private@example.invalid"
SYNTHETIC_METER = "PRIVATE-METER-ONLY"
SYNTHETIC_EAN = "PRIVATE-EAN-ONLY"
SYNTHETIC_HOST = "mqtt.internal.example.invalid"


def _configuration():
    return {
        "cez": {
            "email": SYNTHETIC_EMAIL,
            "electrometer_id": SYNTHETIC_METER,
            "electrometers": [
                {"electrometer_id": SYNTHETIC_METER, "ean": SYNTHETIC_EAN}
            ],
        },
        "mqtt": {"host": SYNTHETIC_HOST, "port": 1883},
    }


def test_startup_summary_excludes_private_values(caplog):
    config = _configuration()
    with caplog.at_level(logging.DEBUG):
        log_startup_summary(config)

    assert "Configured electrometers: 1" in caplog.text
    assert "MQTT broker configuration loaded" in caplog.text
    for value in (
        SYNTHETIC_EMAIL,
        SYNTHETIC_METER,
        SYNTHETIC_EAN,
        SYNTHETIC_HOST,
    ):
        assert value not in caplog.text


def test_auto_meter_selection_is_reported_without_identity(caplog):
    config = _configuration()
    config["cez"]["electrometer_id"] = None
    config["cez"]["electrometers"] = []
    with caplog.at_level(logging.INFO):
        log_startup_summary(config)

    assert "Electrometer selection: automatic" in caplog.text
    assert "No electrometers configured" in caplog.text


def test_malformed_config_error_is_redacted(caplog):
    invalid_json = '[{"electrometer_id":"PRIVATE-METER-ONLY",'
    environment = {
        "CEZ_EMAIL": SYNTHETIC_EMAIL,
        "CEZ_PASSWORD": "synthetic-password",
        "CEZ_ELECTROMETERS": invalid_json,
        "CEZ_ELECTROMETER_ID": SYNTHETIC_METER,
        "CEZ_EAN": SYNTHETIC_EAN,
        "MQTT_HOST": SYNTHETIC_HOST,
    }
    with patch("addon.src.main.os.getenv", side_effect=environment.get):
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit):
            create_config()
    assert "Invalid electrometers configuration" in caplog.text
    for value in (SYNTHETIC_EMAIL, SYNTHETIC_METER, SYNTHETIC_EAN):
        assert value not in caplog.text


def test_login_and_shell_logging_do_not_embed_private_fields():
    auth_source = Path("addon/src/auth.py").read_text(encoding="utf-8")
    shell_source = Path("addon/run.sh").read_text(encoding="utf-8")
    assert 'logger.info("Starting Playwright login")' in auth_source
    assert 'logger.info("Starting Playwright login for %s"' not in auth_source
    assert "Waiting for MQTT broker at ${MQTT_HOST}" not in shell_source
    assert "Error: MQTT broker at ${MQTT_HOST}" not in shell_source
    assert "details suppressed" in shell_source
