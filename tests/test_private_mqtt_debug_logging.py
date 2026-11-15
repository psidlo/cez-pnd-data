"""Synthetic-only privacy regression tests for MQTT and HDO parser logs."""

from __future__ import annotations

import logging
from datetime import datetime
from unittest.mock import MagicMock

from addon.src.hdo_parser import HdoData, _parse_time_ranges
from addon.src.mqtt_publisher import MqttPublisher

PRIVATE_METER = "SYNTHETIC_METER_PRIVATE"
PRIVATE_EAN = "SYNTHETIC_EAN_PRIVATE"
PRIVATE_VALUE = "SYNTHETIC_VALUE_PRIVATE"
PRIVATE_KEY = "SYNTHETIC_UNKNOWN_PRIVATE"


def _publisher():
    client = MagicMock()
    return MqttPublisher(
        client=client,
        electrometer_id=PRIVATE_METER,
        ean=PRIVATE_EAN,
    ), client


def _assert_log_is_redacted(caplog):
    for value in (PRIVATE_METER, PRIVATE_EAN, PRIVATE_VALUE, PRIVATE_KEY):
        assert value not in caplog.text


def test_mqtt_discovery_debug_log_never_contains_topics(caplog):
    publisher, client = _publisher()
    with caplog.at_level(logging.DEBUG):
        publisher.publish_discovery()
    client.publish.assert_called()
    assert "Published MQTT discovery configuration" in caplog.text
    _assert_log_is_redacted(caplog)


def test_sensor_state_and_unrecognized_key_logs_are_redacted(caplog):
    publisher, client = _publisher()
    with caplog.at_level(logging.DEBUG):
        publisher.publish_state(
            {"consumption": 88.77, PRIVATE_KEY: PRIVATE_VALUE}
        )
    client.publish.assert_called()
    assert "Published MQTT sensor state" in caplog.text
    assert "Ignoring unknown sensor key" in caplog.text
    _assert_log_is_redacted(caplog)


def test_hdo_signal_value_and_discovery_are_redacted(caplog):
    publisher, client = _publisher()
    hdo = HdoData(
        is_low_tariff=False,
        next_switch=datetime(2026, 11, 15, 21, 0),
        today_schedule=[("18:00", "21:00")],
        signal_name=PRIVATE_VALUE,
    )
    with caplog.at_level(logging.DEBUG):
        publisher.publish_hdo_state(hdo)
        publisher.publish_hdo_discovery()
    client.publish.assert_called()
    assert "Published HDO sensor state" in caplog.text
    assert "Published HDO discovery configuration" in caplog.text
    _assert_log_is_redacted(caplog)


def test_hdo_malformed_range_does_not_log_raw_content(caplog):
    with caplog.at_level(logging.WARNING):
        result = _parse_time_ranges(PRIVATE_VALUE)
    assert result == []
    assert "Skipping malformed HDO time range" in caplog.text
    _assert_log_is_redacted(caplog)
