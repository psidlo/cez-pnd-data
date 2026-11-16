"""Synthetic broker lifecycle regressions; no network or HA state changes."""

import json
from unittest.mock import MagicMock, call, patch

import pytest

from addon.src.main import MQTTClientWrapper
from addon.src.mqtt_publisher import MqttPublisher


@pytest.fixture
def wrapper():
    with patch("addon.src.main.mqtt_client.Client") as factory:
        value = MQTTClientWrapper("mqtt.example.invalid", 1883, "user", "secret")
    return value, factory.return_value


def test_connect_runs_network_loop_until_connack(wrapper):
    value, client = wrapper
    callback = MagicMock()
    value.set_on_connected(callback)
    client.loop_start.side_effect = lambda: client.on_connect(client, None, {}, 0, None)
    value.connect()
    client.connect.assert_called_once_with("mqtt.example.invalid", 1883, 60)
    client.loop_start.assert_called_once()
    callback.assert_called_once()
    assert value._connected.is_set()


def test_missing_connack_cleans_up_network_thread(wrapper):
    value, client = wrapper
    value._connected = MagicMock()
    value._connected.wait.return_value = False
    with pytest.raises(ConnectionError, match="acknowledgement timed out"):
        value.connect()
    client.disconnect.assert_called_once()
    client.loop_stop.assert_called_once()


def test_rejected_connack_does_not_announce_online(wrapper):
    value, client = wrapper
    callback = MagicMock()
    value.set_on_connected(callback)
    client.on_connect(client, None, {}, 135, None)
    callback.assert_not_called()
    assert not value._connected.is_set()


def test_shutdown_drains_offline_message_before_stopping_loop(wrapper):
    value, client = wrapper
    info = MagicMock()
    info.is_published.return_value = False
    client.publish.return_value = info
    value.publish("cez_pnd/synthetic/availability", "offline")
    value.disconnect()
    info.wait_for_publish.assert_called_once()
    assert client.method_calls[-2:] == [call.disconnect(), call.loop_stop()]


def test_shutdown_stops_loop_even_if_delivery_fails(wrapper):
    value, client = wrapper
    info = MagicMock()
    info.is_published.return_value = False
    info.wait_for_publish.side_effect = RuntimeError("synthetic failure")
    client.publish.return_value = info
    value.publish("cez_pnd/synthetic/availability", "offline")
    value.disconnect()
    client.disconnect.assert_called_once()
    client.loop_stop.assert_called_once()


def test_broker_reconnect_restores_each_meter_without_topic_migration():
    client = MagicMock()
    publisher = MqttPublisher(
        client,
        electrometers=[{"electrometer_id": "111111"}, {"electrometer_id": "222222"}],
    )
    publisher.start()
    restore = client.set_on_connected.call_args.args[0]
    client.reset_mock()
    restore()
    messages = {c.args[0]: c.kwargs["payload"] for c in client.publish.call_args_list}
    for meter in ("111111", "222222"):
        assert messages[f"cez_pnd/{meter}/availability"] == "online"
        topic = f"homeassistant/sensor/cez_pnd_{meter}/consumption/config"
        assert (
            json.loads(messages[topic])["unique_id"] == f"cez_pnd_{meter}_consumption"
        )


def test_discovery_keeps_legacy_units_and_hdo_identity_with_valid_classes():
    client = MagicMock()
    publisher = MqttPublisher(client, electrometer_id="111111")
    publisher.publish_discovery()
    messages = {
        c.args[0]: json.loads(c.kwargs["payload"])
        for c in client.publish.call_args_list
    }
    rv = messages["homeassistant/sensor/cez_pnd_111111/reactive/config"]
    assert rv["unit_of_measurement"] == "kW"
    assert rv["device_class"] is None
    hdo = messages["homeassistant/sensor/cez_pnd_111111/hdo_low_tariff_active/config"]
    assert hdo["device_class"] is None
    assert hdo["unique_id"] == "cez_pnd_111111_hdo_low_tariff_active"


def test_poll_publication_survives_a_previous_disconnected_delivery(wrapper):
    value, client = wrapper
    previous = MagicMock()
    previous.is_published.side_effect = RuntimeError("synthetic disconnect")
    value._pending = [previous]
    value.publish("cez_pnd/synthetic/consumption/state", "0.123")
    client.publish.assert_called_once()
