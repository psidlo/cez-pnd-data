"""Synthetic compatibility checks for historical window and PND rejection handling."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from addon.src import main as runtime


@pytest.mark.asyncio
async def test_rejected_historical_assembly_aborts_remaining_requests(monkeypatch):
    from tests.test_pnd_history_fetch import fake_fetch_environment

    secret = "SYNTHETIC_SECRET_NEVER_LOG"
    configs = [
        {"id": -1003, "name": "profile_all"},
        {"id": -1021, "name": "daily_consumption"},
    ]
    fetcher, context, browser = fake_fetch_environment(
        monkeypatch, error=runtime.PndRequestRejected(secret, status_code=429)
    )
    with pytest.raises(runtime.PndRequestRejected):
        await fetcher.fetch_all(
            [],
            "synthetic-meter",
            configs,
            archive_day=datetime(2026, 11, 14),
            archive_mode=True,
        )
    assert fetcher._fetch_one_in_context.await_count == 1
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_historical_http_429_activates_backoff_without_body_access():
    fetcher = runtime.PndFetcher()
    response = MagicMock()
    response.status = 429
    response.text = AsyncMock(
        side_effect=AssertionError("rejection body must not be read")
    )
    context = MagicMock()
    context.request.post = AsyncMock(return_value=response)

    with pytest.raises(runtime.PndRequestRejected) as caught:
        await fetcher._fetch_one_in_context(
            context,
            "synthetic-meter",
            -1003,
            "14.11.2026 00:00",
            "15.11.2026 00:00",
        )
    assert caught.value.status_code == 429
    assert fetcher.cooldown_seconds_remaining > 0
    response.text.assert_not_awaited()
    with pytest.raises(runtime.PndRequestRejected, match="cooldown"):
        await fetcher._fetch_one_in_context(
            context,
            "synthetic-meter",
            -1021,
            "14.11.2026 00:00",
            "14.11.2026 23:59",
        )
    context.request.post.assert_awaited_once()
