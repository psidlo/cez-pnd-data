"""Opt-in archive wiring tests: synthetic, no CEZ, SQLite or MQTT network."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from addon.src.archive_backfill import BackfillResult
from addon.src.archive_runtime import ArchiveCycle, archive_settings_from_env
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
    assert first.args[7] == ""
    assert second.args[7] == ""
    assert first.args[5] == 2
    assert second.args[5] == 1
    cycle.close()
    store.close.assert_not_called()


@pytest.mark.asyncio
async def test_archive_rejection_stops_remaining_meters(caplog):
    store = MagicMock()
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
