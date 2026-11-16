"""Synthetic regression tests for privacy-safe runtime orchestration logs."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from addon.src.dip_client import DipTokenError
from addon.src.orchestrator import Orchestrator, OrchestratorConfig

PRIVATE = "SYNTHETIC_PRIVATE_VALUE"
METER = "SYNTHETIC_PRIVATE_METER"


def _make_orchestrator(*, auth_error=None, fetcher=None, hdo_fetcher=None):
    auth = MagicMock()
    auth.ensure_session = AsyncMock()
    if auth_error:
        auth.ensure_session.side_effect = auth_error
    else:
        auth.ensure_session.return_value = MagicMock(
            cookies=[], has_live_context=True, context=MagicMock()
        )
    mqtt = MagicMock()
    config = OrchestratorConfig(
        electrometers=[{"electrometer_id": METER, "ean": "SYNTHETIC_EAN"}],
        max_retries=1,
        retry_base_delay_seconds=0.001,
    )
    if fetcher is None:
        fetcher = AsyncMock(return_value={})
    orchestrator = Orchestrator(
        config=config,
        auth_client=auth,
        fetcher=fetcher,
        mqtt_publisher=mqtt,
        hdo_fetcher=hdo_fetcher,
    )
    return orchestrator


def _assert_private_values_absent(caplog):
    assert PRIVATE not in caplog.text
    assert METER not in caplog.text
    assert "SYNTHETIC_EAN" not in caplog.text


@pytest.mark.asyncio
async def test_auth_exception_never_logs_private_data(caplog):
    orch = _make_orchestrator(auth_error=RuntimeError(PRIVATE))
    with caplog.at_level(logging.DEBUG):
        await orch.run_once()
    assert "Auth failure" in caplog.text
    _assert_private_values_absent(caplog)


@pytest.mark.asyncio
async def test_batch_fetch_error_is_safely_logged(caplog):
    class BatchFetcher:
        async def fetch_all(self, *_args):
            raise RuntimeError(PRIVATE)

        async def fetch(self, *_args, **_kwargs):
            raise AssertionError("unexpected fallback")

    fetcher = BatchFetcher()
    orch = _make_orchestrator(fetcher=fetcher.fetch)
    with caplog.at_level(logging.DEBUG):
        await orch.run_once()
    assert "Batch fetch_all failed" in caplog.text
    _assert_private_values_absent(caplog)


@pytest.mark.asyncio
async def test_hdo_errors_are_redacted_but_identifiable(caplog):
    fetch = AsyncMock(return_value={})
    hdo = AsyncMock(side_effect=DipTokenError(PRIVATE))
    orch = _make_orchestrator(fetcher=fetch, hdo_fetcher=hdo)
    with caplog.at_level(logging.DEBUG):
        await orch.run_once()
    assert "HDO_TOKEN_ERROR" in caplog.text
    _assert_private_values_absent(caplog)


@pytest.mark.asyncio
async def test_generic_hdo_error_does_not_reveal_url(caplog):
    fetch = AsyncMock(return_value={})
    hdo = AsyncMock(side_effect=RuntimeError(PRIVATE))
    orch = _make_orchestrator(fetcher=fetch, hdo_fetcher=hdo)
    with caplog.at_level(logging.DEBUG):
        await orch.run_once()
    assert "HDO_FETCH_ERROR" in caplog.text
    _assert_private_values_absent(caplog)


@pytest.mark.asyncio
async def test_retry_failure_keeps_safe_error_code(caplog):
    fetch = AsyncMock(side_effect=RuntimeError(PRIVATE))
    orch = _make_orchestrator(fetcher=fetch)
    with caplog.at_level(logging.DEBUG):
        result = await orch._fetch_with_retry([])
    assert result is None
    assert "CEZ_FETCH_ERROR" in caplog.text
    _assert_private_values_absent(caplog)
