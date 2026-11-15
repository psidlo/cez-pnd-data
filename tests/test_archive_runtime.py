"""Opt-in archive wiring tests: synthetic, no CEZ, SQLite or MQTT network."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from addon.src.archive_backfill import BackfillResult
from addon.src.archive_runtime import (
    ArchiveCycle,
    archive_meters_from_env,
    archive_settings_from_env,
)
from addon.src.orchestrator import Orchestrator, OrchestratorConfig

METER_1 = "SYNTHETIC_METER_ONE"
METER_2 = "SYNTHETIC_METER_TWO"
EAN_1 = "SYNTHETIC_EAN_ONE"
EAN_2 = "SYNTHETIC_EAN_TWO"


def test_archive_is_disabled_by_default_even_if_other_settings_are_bad():
    assert archive_settings_from_env({}) == (False, "", 0)
    assert archive_settings_from_env({
        "CEZ_ARCHIVE_ENABLED": "false",
        "CEZ_ARCHIVE_START_DATE": "PRIVATE_INVALID",
        "CEZ_ARCHIVE_MAX_DAYS": "PRIVATE_INVALID",
    }) == (False, "", 0)


@pytest.mark.parametrize("start,limit", [
    ("", "1"), ("2026-14-01", "1"), ("2026-09-01", "0"),
    ("2026-09-01", "63"), ("2026-09-01", "SECRET"),
])
def test_enabled_archive_rejects_invalid_options_without_values(start, limit):
    with pytest.raises(ValueError) as error:
        archive_settings_from_env({
            "CEZ_ARCHIVE_ENABLED": "true",
            "CEZ_ARCHIVE_START_DATE": start,
            "CEZ_ARCHIVE_MAX_DAYS": limit,
        })
    assert start not in str(error.value) if start else True
    assert limit not in str(error.value) if limit == "SECRET" else True


def test_enabled_archive_configuration_is_bounded():
    assert archive_settings_from_env({
        "CEZ_ARCHIVE_ENABLED": "True",
        "CEZ_ARCHIVE_START_DATE": "2026-09-01",
        "CEZ_ARCHIVE_MAX_DAYS": "2",
    }) == (True, "2026-09-01", 2)


@pytest.mark.asyncio
async def test_archive_budget_shared_across_all_meters_without_ean_guessing():
    store = MagicMock()
    client = MagicMock()
    store.db.execute.return_value.fetchone.side_effect = [
        (EAN_1, "SYNTHETIC_EXPORT_EAN_ONE"),
        (EAN_2, "SYNTHETIC_EXPORT_EAN_TWO"),
    ]
    cycle = ArchiveCycle(
        client, store=store, start_date="2026-09-01",
        max_days=2, rejection_error=RuntimeError,
    )
    cycle.backfill.run = AsyncMock(side_effect=[
        BackfillResult(planned=2, attempted=1, succeeded=1),
        BackfillResult(planned=2, attempted=1, succeeded=1),
    ])
    await cycle.run([], [
        {"electrometer_id": METER_1, "ean": EAN_1},
        {"electrometer_id": METER_2, "ean": EAN_2},
        {"electrometer_id": "THIRD", "ean": "THIRD_EAN"},
    ])
    assert cycle.backfill.run.await_count == 2
    first, second = cycle.backfill.run.await_args_list
    assert first.args[2] == METER_1
    assert second.args[2] == METER_2
    assert first.args[6] == EAN_1
    assert second.args[6] == EAN_2
    assert first.args[7] == "SYNTHETIC_EXPORT_EAN_ONE"
    assert second.args[7] == "SYNTHETIC_EXPORT_EAN_TWO"
    assert first.args[5] == 2
    assert second.args[5] == 1
    cycle.close()
    store.close.assert_not_called()


@pytest.mark.asyncio
async def test_archive_rejection_stops_remaining_meters(caplog):
    store = MagicMock()
    store.db.execute.return_value.fetchone.return_value = (
        EAN_1, "SYNTHETIC_EXPORT_EAN_ONE",
    )
    cycle = ArchiveCycle(
        MagicMock(), store=store, start_date="2026-09-01",
        max_days=3, rejection_error=RuntimeError,
    )
    cycle.backfill.run = AsyncMock(return_value=BackfillResult(
        planned=3, attempted=1, failed=1, paused_by_rejection=True
    ))
    with caplog.at_level(logging.WARNING):
        await cycle.run([], [
            {"electrometer_id": METER_1, "ean": EAN_1},
            {"electrometer_id": METER_2, "ean": EAN_2},
        ])
    cycle.backfill.run.assert_awaited_once()
    assert EAN_1 not in caplog.text and METER_1 not in caplog.text


@pytest.mark.asyncio
async def test_optional_hook_failure_does_not_interrupt_normal_poll(caplog):
    auth = MagicMock()
    auth.ensure_session = AsyncMock(return_value=MagicMock(cookies=[]))
    mqtt = MagicMock()
    hook = AsyncMock(side_effect=RuntimeError("SYNTHETIC_SECRET"))
    orchestrator = Orchestrator(
        config=OrchestratorConfig(electrometers=[]),
        auth_client=auth,
        fetcher=AsyncMock(return_value={}),
        mqtt_publisher=mqtt,
        hdo_fetcher=None,
        archive_hook=hook,
    )
    with caplog.at_level(logging.ERROR):
        await orchestrator.run_once()
    hook.assert_awaited_once()
    assert "Optional PND archive cycle failed" in caplog.text
    assert "SYNTHETIC_SECRET" not in caplog.text


@pytest.mark.asyncio
async def test_existing_metadata_is_not_overwritten_with_supply_ean(caplog):
    store = MagicMock()
    store.db.execute.return_value.fetchone.return_value = (
        "SYNTHETIC_STORED_IMPORT", "SYNTHETIC_STORED_EXPORT",
    )
    cycle = ArchiveCycle(
        MagicMock(), store=store, start_date="2026-09-01",
        max_days=1, rejection_error=RuntimeError,
    )
    cycle.backfill.run = AsyncMock(return_value=BackfillResult(attempted=1))
    with caplog.at_level(logging.WARNING):
        await cycle.run([], [{"electrometer_id": METER_1, "ean": EAN_1}])
    called = cycle.backfill.run.await_args
    assert called.args[6:8] == (
        "SYNTHETIC_STORED_IMPORT", "SYNTHETIC_STORED_EXPORT"
    )
    assert METER_1 not in caplog.text


@pytest.mark.asyncio
async def test_missing_explicit_ean_mapping_skips_meter_without_write(caplog):
    store = MagicMock()
    store.db.execute.return_value.fetchone.return_value = None
    cycle = ArchiveCycle(
        MagicMock(), store=store, start_date="2026-09-01",
        max_days=1, rejection_error=RuntimeError,
    )
    cycle.backfill.run = AsyncMock()
    with caplog.at_level(logging.WARNING):
        await cycle.run([], [{"electrometer_id": METER_1, "ean": EAN_1}])
    cycle.backfill.run.assert_not_awaited()
    assert METER_1 not in caplog.text
    assert EAN_1 not in caplog.text


@pytest.mark.asyncio
async def test_new_meter_accepts_two_explicit_distinct_eans():
    store = MagicMock()
    store.db.execute.return_value.fetchone.return_value = None
    cycle = ArchiveCycle(
        MagicMock(), store=store, start_date="2026-09-01",
        max_days=1, rejection_error=RuntimeError,
    )
    cycle.backfill.run = AsyncMock(return_value=BackfillResult(attempted=1))
    await cycle.run([], [{
        "electrometer_id": METER_1, "ean": "SUPPLY_ONLY",
        "archive_import_ean": EAN_1,
        "archive_export_ean": EAN_2,
    }])
    assert cycle.backfill.run.await_args.args[6:8] == (EAN_1, EAN_2)


@pytest.mark.asyncio
async def test_explicit_metadata_conflict_is_rejected_without_data_loss(caplog):
    store = MagicMock()
    store.db.execute.return_value.fetchone.return_value = (EAN_1, EAN_2)
    cycle = ArchiveCycle(
        MagicMock(), store=store, start_date="2026-09-01",
        max_days=1, rejection_error=RuntimeError,
    )
    cycle.backfill.run = AsyncMock()
    with caplog.at_level(logging.WARNING):
        await cycle.run([], [{
            "electrometer_id": METER_1, "ean": "SUPPLY_ONLY",
            "archive_import_ean": "SYNTHETIC_CONFLICT_PRIVATE",
        }])
    cycle.backfill.run.assert_not_awaited()
    assert "SYNTHETIC_CONFLICT_PRIVATE" not in caplog.text
    assert METER_1 not in caplog.text


def test_archive_meter_selection_keeps_legacy_history_separate_from_mqtt():
    env = {
        "CEZ_ARCHIVE_METER_IDS": '["111111","222222"]',
        "CEZ_IMPORT_EAN": "SYNTHETIC_IMPORT",
        "CEZ_EXPORT_EAN": "SYNTHETIC_EXPORT",
    }
    meters = archive_meters_from_env(
        env, [{"electrometer_id": "222222", "ean": "MQTT_EAN"}]
    )
    assert [m["electrometer_id"] for m in meters] == ["111111", "222222"]
    assert all(m["archive_import_ean"] == "SYNTHETIC_IMPORT" for m in meters)
    assert all(m["archive_export_ean"] == "SYNTHETIC_EXPORT" for m in meters)


def test_archive_meters_with_no_separate_list_keep_current_mqtt_selection():
    mqtt = [{"electrometer_id": "333333", "ean": "MQTT_EAN"}]
    assert archive_meters_from_env({"CEZ_ARCHIVE_METER_IDS": "[]"}, mqtt) == mqtt


@pytest.mark.parametrize("invalid", [
    "not-json", '["1234", 3]', '["private-not-numeric"]',
    '{"wrong":"shape"}',
])
def test_legacy_meter_list_is_validated_without_echoing_input(invalid):
    with pytest.raises(ValueError) as e:
        archive_meters_from_env({"CEZ_ARCHIVE_METER_IDS": invalid}, [])
    assert invalid not in str(e.value)


def test_half_configured_archive_ean_pair_rejected_without_private_values():
    with pytest.raises(ValueError) as e:
        archive_meters_from_env({
            "CEZ_ARCHIVE_METER_IDS": '["111111"]',
            "CEZ_IMPORT_EAN": "SYNTHETIC_SECRET",
        }, [])
    assert "SYNTHETIC_SECRET" not in str(e.value)


def test_archive_max_days_matches_legacy_50_day_setting():
    assert archive_settings_from_env({
        "CEZ_ARCHIVE_ENABLED": "true",
        "CEZ_ARCHIVE_START_DATE": "2026-09-01",
        "CEZ_ARCHIVE_MAX_DAYS": "50",
    }) == (True, "2026-09-01", 50)


def test_external_mqtt_options_present_without_private_defaults():
    from pathlib import Path
    script = Path("addon/run.sh").read_text(encoding="utf-8")
    config = Path("addon/config.yaml").read_text(encoding="utf-8")
    for name in ("mqtt_host", "mqtt_port", "mqtt_user", "mqtt_password"):
        assert f'read_option {name} ' in script
        assert f"  {name}:" in config
    assert "CEZ_ARCHIVE_METER_IDS" in script
    assert "CEZ_ARCHIVE_MAX_DAYS" in script
    assert "Waiting for MQTT broker at " not in script
