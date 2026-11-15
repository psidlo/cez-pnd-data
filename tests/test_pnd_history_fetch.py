"""Synthetic fetcher tests: all Playwright operations are mocks, no network."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from addon.src import main as runtime


PROFILES = [
    {"id": -1003, "name": "profile_all"},
    {"id": -1021, "name": "daily_consumption"},
]


def fake_fetch_environment(monkeypatch, *, payload=None, error=None):
    """Return a real fetcher with fake browser and API internals."""
    page = SimpleNamespace(goto=AsyncMock(), close=AsyncMock())
    context = SimpleNamespace(
        add_cookies=AsyncMock(),
        new_page=AsyncMock(return_value=page),
        close=AsyncMock(),
        request=SimpleNamespace(
            post=AsyncMock(return_value=SimpleNamespace(status=400))
        ),
    )
    browser = SimpleNamespace(close=AsyncMock())
    pw = SimpleNamespace(
        chromium=SimpleNamespace(launch=AsyncMock(return_value=browser))
    )

    class PlaywrightManager:
        async def __aenter__(self):
            return pw

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        runtime, "_get_async_playwright", lambda: (lambda: PlaywrightManager())
    )
    monkeypatch.setattr(runtime.asyncio, "sleep", AsyncMock())
    fetcher = runtime.PndFetcher()
    fetcher._create_browser_context = AsyncMock(return_value=context)
    if error is None:
        fetcher._fetch_one_in_context = AsyncMock(
            return_value=payload if payload is not None else {"hasData": True}
        )
    else:
        fetcher._fetch_one_in_context = AsyncMock(side_effect=error)
    return fetcher, context, browser


@pytest.mark.asyncio
async def test_historical_fetch_uses_midnight_profile_endpoint(monkeypatch):
    fetcher, context, browser = fake_fetch_environment(monkeypatch)
    result = await fetcher.fetch_all(
        [], "synthetic-meter", PROFILES,
        archive_day=datetime(2026, 11, 14), archive_mode=True,
    )
    assert set(result) == {"profile_all", "daily_consumption"}
    calls = fetcher._fetch_one_in_context.await_args_list
    assert calls[0].args[3:] == ("14.11.2026 00:00", "15.11.2026 00:00")
    assert calls[1].args[3:] == ("14.11.2026 00:00", "14.11.2026 23:59")
    assert calls[0].args[1:3] == ("synthetic-meter", -1003)
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_historical_fetch_preserves_valid_empty_assemblies(monkeypatch):
    fetcher, _, _ = fake_fetch_environment(monkeypatch, payload={"hasData": False})
    result = await fetcher.fetch_all(
        [], "synthetic-meter", PROFILES,
        archive_day=datetime(2026, 11, 14), archive_mode=True,
    )
    assert set(result) == {"profile_all", "daily_consumption"}
    assert all(value["hasData"] is False for value in result.values())
    assert fetcher._fetch_one_in_context.await_count == 2


@pytest.mark.asyncio
async def test_archive_mode_disables_yesterday_fallback(monkeypatch):
    configs = [{"id": -1027, "name": "daily_registers", "fallback_yesterday": True}]
    fetcher, _, _ = fake_fetch_environment(monkeypatch, payload={"hasData": False})
    result = await fetcher.fetch_all(
        [], "synthetic-meter", configs,
        archive_day=datetime(2026, 11, 14), archive_mode=True,
    )
    assert "daily_registers" in result
    fetcher._fetch_one_in_context.assert_awaited_once()


@pytest.mark.asyncio
async def test_live_mode_still_filters_empty_payloads(monkeypatch):
    configs = [{"id": -1003, "name": "profile_all"}]
    fetcher, _, _ = fake_fetch_environment(monkeypatch, payload={"hasData": False})
    result = await fetcher.fetch_all([], "synthetic-meter", configs)
    assert result == {}
    fetcher._fetch_one_in_context.assert_awaited_once()


@pytest.mark.asyncio
async def test_history_api_failure_propagates_without_loggable_response(
    monkeypatch, caplog
):
    secret = "DO_NOT_PRINT_PRIVATE_URL_OR_TOKEN"
    fetcher, context, browser = fake_fetch_environment(
        monkeypatch, error=RuntimeError(secret)
    )
    with pytest.raises(RuntimeError, match=secret):
        await fetcher.fetch_all(
            [], "synthetic-meter", PROFILES,
            archive_day=datetime(2026, 11, 14), archive_mode=True,
        )
    assert secret not in caplog.text
    assert fetcher._fetch_one_in_context.await_count == 1
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_live_assembly_error_still_skipped(monkeypatch):
    fetcher, _, _ = fake_fetch_environment(
        monkeypatch, error=RuntimeError("synthetic transport failure")
    )
    result = await fetcher.fetch_all([], "synthetic-meter", PROFILES)
    assert result == {}
    assert fetcher._fetch_one_in_context.await_count == 2


@pytest.mark.asyncio
async def test_invalid_historical_mode_fails_before_browser(monkeypatch):
    monkeypatch.setattr(
        runtime, "_get_async_playwright",
        Mock(side_effect=AssertionError("Browser should not start")),
    )
    with pytest.raises(ValueError, match="archive_day is required"):
        await runtime.PndFetcher().fetch_all(
            [], "synthetic-meter", PROFILES, archive_mode=True
        )


@pytest.mark.asyncio
async def test_empty_config_skips_browser_without_error(monkeypatch):
    monkeypatch.setattr(
        runtime, "_get_async_playwright",
        Mock(side_effect=AssertionError("Browser should not start")),
    )
    assert await runtime.PndFetcher().fetch_all(
        [], "synthetic-meter", [],
        archive_day=datetime(2026, 11, 14), archive_mode=True,
    ) == {}
