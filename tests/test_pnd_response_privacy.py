"""PND error-path regressions use synthetic strings and mocked responses only."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from addon.src.main import PndFetcher, PndFetchError, PndRequestRejected
from addon.src.orchestrator import SessionExpiredError
from addon.src.pnd_response_safety import safe_content_kind, safe_html_category

PRIVATE = "SYNTHETIC_DO_NOT_LOG"


def _context(status=200, mime="application/json", body=None, json_error=None):
    response = AsyncMock()
    response.status = status
    response.headers = {"content-type": mime}
    response.text = AsyncMock(return_value=body or PRIVATE)
    response.json = (
        AsyncMock(side_effect=json_error)
        if json_error
        else AsyncMock(return_value={"hasData": True, "values": []})
    )
    context = AsyncMock()
    context.request.post = AsyncMock(return_value=response)
    return context, response


async def _fetch_one(fetcher, context):
    return await fetcher._fetch_one_in_context(
        context, "synthetic-meter", -1003, "14.11.2026 00:00", "15.11.2026 00:00"
    )


def test_fixed_response_categories_hide_untrusted_headers_and_bodies():
    assert safe_content_kind("text/html; token=" + PRIVATE) == "html"
    assert safe_content_kind("application/json; token=" + PRIVATE) == "json"
    assert safe_content_kind(None) == "unknown"
    assert safe_html_category("Request Rejected " + PRIVATE) == "portal-rejection"
    login_html = '<input name="username" value="' + PRIVATE
    assert safe_html_category(login_html) == "login-page"
    assert safe_html_category("Odstávka " + PRIVATE) == "maintenance"
    assert PRIVATE not in safe_html_category(PRIVATE)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429])
async def test_http_rejection_starts_cooldown_without_reading_body(status, caplog):
    ctx, response = _context(status=status)
    fetcher = PndFetcher()
    with caplog.at_level(logging.DEBUG), pytest.raises(PndRequestRejected) as caught:
        await _fetch_one(fetcher, ctx)
    assert caught.value.status_code == status
    assert fetcher.cooldown_seconds_remaining > 0
    response.text.assert_not_awaited()
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
async def test_401_is_session_expired():
    ctx, response = _context(status=401)
    with pytest.raises(SessionExpiredError):
        await _fetch_one(PndFetcher(), ctx)
    response.text.assert_not_awaited()


@pytest.mark.asyncio
async def test_503_does_not_start_rejection_cooldown():
    ctx, response = _context(status=503)
    fetcher = PndFetcher()
    with pytest.raises(PndFetchError) as error:
        await _fetch_one(fetcher, ctx)
    assert error.value.status_code == 503
    assert not isinstance(error.value, PndRequestRejected)
    assert fetcher.cooldown_seconds_remaining == 0
    response.text.assert_not_awaited()


@pytest.mark.asyncio
async def test_portal_html_rejection_is_redacted(caplog):
    ctx, response = _context(
        mime="text/html; secret=" + PRIVATE,
        body="<html>The requested URL was rejected " + PRIVATE + "</html>",
    )
    fetcher = PndFetcher()
    with caplog.at_level(logging.DEBUG), pytest.raises(PndRequestRejected):
        await _fetch_one(fetcher, ctx)
    assert fetcher.cooldown_seconds_remaining > 0
    response.text.assert_awaited_once()
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
async def test_login_html_requires_reauthentication_not_backoff():
    ctx, _ = _context(mime="text/html", body='<input name="username">')
    fetcher = PndFetcher()
    with pytest.raises(SessionExpiredError):
        await _fetch_one(fetcher, ctx)
    assert fetcher.cooldown_seconds_remaining == 0


@pytest.mark.asyncio
async def test_non_json_mime_does_not_leak_header_or_body(caplog):
    ctx, _ = _context(mime="text/html; secret=" + PRIVATE)
    with caplog.at_level(logging.DEBUG), pytest.raises(PndFetchError) as error:
        await _fetch_one(PndFetcher(), ctx)
    assert "non-JSON" in str(error.value)
    assert PRIVATE not in str(error.value)
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
async def test_json_parse_error_does_not_leak_exception_or_body(caplog):
    ctx, response = _context(json_error=ValueError("token=" + PRIVATE))
    with caplog.at_level(logging.DEBUG), pytest.raises(PndFetchError) as error:
        await _fetch_one(PndFetcher(), ctx)
    assert "JSON parse failed" in str(error.value)
    assert PRIVATE not in str(error.value)
    assert PRIVATE not in caplog.text
    response.text.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_json_preserves_original_behavior():
    ctx, _ = _context()
    result = await _fetch_one(PndFetcher(), ctx)
    assert result["hasData"] is True


@pytest.mark.asyncio
async def test_rejection_aborts_batch_and_blocks_next_cycle(caplog):
    fetcher = PndFetcher()
    warmup = AsyncMock()
    warmup.status = 200
    rejected = AsyncMock()
    rejected.status = 429
    context = AsyncMock()
    context.request.post = AsyncMock(side_effect=[warmup, rejected])
    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)
    playwright = AsyncMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    manager = AsyncMock()
    manager.__aenter__ = AsyncMock(return_value=playwright)
    manager.__aexit__ = AsyncMock(return_value=False)
    configs = [
        {"id": -1003, "name": "profile_all"},
        {"id": -1012, "name": "profile_consumption_reactive"},
    ]
    with (
        patch("addon.src.main._get_async_playwright", return_value=lambda: manager),
        patch("addon.src.main.asyncio.sleep", new_callable=AsyncMock),
        caplog.at_level(logging.DEBUG),
    ):
        with pytest.raises(PndRequestRejected):
            await fetcher.fetch_all([], "synthetic-meter", configs)
        assert context.request.post.await_count == 2
        with pytest.raises(PndRequestRejected, match="cooldown"):
            await fetcher.fetch_all([], "synthetic-meter", configs)
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
async def test_batch_exception_text_is_never_logged(caplog):
    fetcher = PndFetcher()
    warmup = AsyncMock()
    warmup.status = 200
    context = AsyncMock()
    context.request.post = AsyncMock(
        side_effect=[warmup, RuntimeError("token=" + PRIVATE)]
    )
    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)
    playwright = AsyncMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    manager = AsyncMock()
    manager.__aenter__ = AsyncMock(return_value=playwright)
    manager.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("addon.src.main._get_async_playwright", return_value=lambda: manager),
        patch("addon.src.main.asyncio.sleep", new_callable=AsyncMock),
        caplog.at_level(logging.DEBUG),
    ):
        result = await fetcher.fetch_all(
            [], "synthetic-meter", [{"id": -1003, "name": "profile_all"}]
        )
    assert result == {}
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429])
async def test_rejected_warmup_aborts_before_real_fetch(status, caplog):
    fetcher = PndFetcher()
    warmup = AsyncMock()
    warmup.status = status
    context = AsyncMock()
    context.request.post = AsyncMock(return_value=warmup)
    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)
    playwright = AsyncMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    manager = AsyncMock()
    manager.__aenter__ = AsyncMock(return_value=playwright)
    manager.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("addon.src.main._get_async_playwright", return_value=lambda: manager),
        patch("addon.src.main.asyncio.sleep", new_callable=AsyncMock),
        caplog.at_level(logging.DEBUG),
    ):
        with pytest.raises(PndRequestRejected) as caught:
            await fetcher.fetch_all(
                [], "synthetic-meter", [{"id": -1003, "name": "profile_all"}]
            )
    assert caught.value.status_code == status
    assert context.request.post.await_count == 1
    assert fetcher.cooldown_seconds_remaining > 0
    assert PRIVATE not in caplog.text
