from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from addon.src.dip_client import (
    DipClient,
    DipFetchError,
    DipMaintenanceError,
    DipTokenError,
    _safe_token_diagnostics,
)


def _mock_page(
    token: str | None = "test-token",
    fetch_result: dict | None = None,
    wait_for_function_error: Exception | None = None,
    goto_error: Exception | None = None,
    evaluate_error: Exception | None = None,
) -> AsyncMock:
    page = AsyncMock()

    if goto_error:
        page.goto = AsyncMock(side_effect=goto_error)
    else:
        page.goto = AsyncMock()

    if wait_for_function_error:
        page.wait_for_function = AsyncMock(side_effect=wait_for_function_error)
    else:
        page.wait_for_function = AsyncMock()

    async def evaluate_side_effect(expr, args=None):
        if evaluate_error:
            raise evaluate_error
        if args is None:
            if wait_for_function_error:
                raise wait_for_function_error
            return token
        return fetch_result or {
            "status": 200,
            "contentType": "application/json",
            "body": '{"data": {"signal": "test"}}',
        }

    page.evaluate = AsyncMock(side_effect=evaluate_side_effect)
    page.close = AsyncMock()
    return page


def _mock_context(page: AsyncMock) -> Mock:
    context = Mock()
    context.new_page = AsyncMock(return_value=page)
    return context


@pytest.mark.asyncio
async def test_fetch_hdo_returns_data_field():
    expected_data = {"signal": "EVV2", "casy": ["08:00-16:00"]}
    page = _mock_page(
        fetch_result={
            "status": 200,
            "contentType": "application/json",
            "body": json.dumps({"data": expected_data}),
        }
    )
    context = _mock_context(page)

    result = await DipClient().fetch_hdo(context, ean="123")

    assert result == expected_data
    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_token_not_found_in_local_storage():
    page = _mock_page(wait_for_function_error=asyncio.TimeoutError())
    context = _mock_context(page)

    with pytest.raises(DipTokenError, match="Token bootstrap failed"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_playwright_timeout_is_token_error():
    page = _mock_page(
        wait_for_function_error=PlaywrightTimeoutError("Timeout 30000ms exceeded")
    )
    context = _mock_context(page)

    with pytest.raises(DipTokenError, match="Token bootstrap failed"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_empty_token():
    page = _mock_page(token="")
    context = _mock_context(page)

    with pytest.raises(DipTokenError, match="Token bootstrap failed"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_maintenance_on_400():
    page = _mock_page(
        fetch_result={"status": 400, "contentType": "application/json", "body": "{}"}
    )
    context = _mock_context(page)

    with pytest.raises(
        DipMaintenanceError, match="Signals endpoint unavailable \\(HTTP 400\\)"
    ):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_maintenance_on_503():
    page = _mock_page(
        fetch_result={"status": 503, "contentType": "application/json", "body": "{}"}
    )
    context = _mock_context(page)

    with pytest.raises(
        DipMaintenanceError, match="Signals endpoint unavailable \\(HTTP 503\\)"
    ):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_fetch_error_on_500():
    page = _mock_page(
        fetch_result={"status": 500, "contentType": "application/json", "body": "{}"}
    )
    context = _mock_context(page)

    with pytest.raises(DipFetchError, match="Signals request failed: HTTP 500"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_maintenance_on_html_content():
    page = _mock_page(
        fetch_result={
            "status": 200,
            "contentType": "text/html; charset=UTF-8",
            "body": "<html>maintenance</html>",
        }
    )
    context = _mock_context(page)

    with pytest.raises(DipMaintenanceError, match="Signals endpoint returned HTML"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_fetch_error_on_missing_data_key():
    page = _mock_page(
        fetch_result={
            "status": 200,
            "contentType": "application/json",
            "body": '{"other": "value"}',
        }
    )
    context = _mock_context(page)

    with pytest.raises(DipFetchError, match="Data missing from response"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_fetch_error_on_goto_timeout():
    page = _mock_page(goto_error=asyncio.TimeoutError())
    context = _mock_context(page)

    with pytest.raises(DipFetchError, match="Fetch failed:"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_fetch_error_on_generic_exception():
    page = _mock_page(evaluate_error=RuntimeError("something went wrong"))
    context = _mock_context(page)

    with pytest.raises(DipTokenError, match="Token bootstrap failed"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_page_closed_on_success():
    page = _mock_page()
    context = _mock_context(page)

    await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_page_closed_on_error():
    page = _mock_page(
        fetch_result={"status": 500, "contentType": "application/json", "body": "{}"}
    )
    context = _mock_context(page)

    with pytest.raises(DipFetchError):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_correct_url_construction():
    page = _mock_page()
    context = _mock_context(page)

    await DipClient().fetch_hdo(context, ean="8591234567890")

    evaluate_calls = page.evaluate.call_args_list
    fetch_call = [c for c in evaluate_calls if len(c.args) > 1][0]
    args = fetch_call.args[1]
    assert "8591234567890" in args["url"]
    assert "signals/8591234567890" in args["url"]
    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_token_used_in_fetch():
    page = _mock_page(token="secret-token-xyz")
    context = _mock_context(page)

    await DipClient().fetch_hdo(context, ean="123")

    evaluate_calls = page.evaluate.call_args_list
    fetch_call = [c for c in evaluate_calls if len(c.args) > 1][0]
    args = fetch_call.args[1]
    assert args["token"] == "secret-token-xyz"
    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_preserves_return_format():
    expected_data = {
        "signal": "EVV2",
        "casy": ["08:00-16:00"],
        "den": "pondeli",
        "datum": "16.02.2026",
    }
    page = _mock_page(
        fetch_result={
            "status": 200,
            "contentType": "application/json",
            "body": json.dumps({"data": expected_data, "extra": "ignored"}),
        }
    )
    context = _mock_context(page)

    result = await DipClient().fetch_hdo(context, ean="123")

    assert result == expected_data
    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_navigates_to_dip_portal():
    page = _mock_page()
    context = _mock_context(page)

    await DipClient().fetch_hdo(context, ean="123")

    assert page.goto.await_count == 2
    assert (
        page.goto.call_args_list[0].args[0] == "https://dip.cezdistribuce.cz/irj/portal"
    )
    call_args = page.goto.call_args
    assert "dip.cezdistribuce.cz/irj/portal/prehled-om" in call_args[0][0]
    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_initializes_dashboard_before_explicit_token_bootstrap():
    page = _mock_page()
    context = _mock_context(page)

    await DipClient().fetch_hdo(context, ean="123")

    page.wait_for_function.assert_awaited_once()
    assert page.wait_for_function.call_args.kwargs["timeout"] == 5000
    assert "/rest-auth-api?path=/token/get" in page.evaluate.call_args_list[0].args[0]
    page.close.assert_called_once()


def test_is_html_content_type_detects_html():
    assert DipClient._is_html_content_type("text/html") is True
    assert DipClient._is_html_content_type("text/html; charset=UTF-8") is True
    assert DipClient._is_html_content_type("TEXT/HTML") is True
    assert DipClient._is_html_content_type("application/xhtml+xml") is False


def test_is_html_content_type_rejects_json():
    assert DipClient._is_html_content_type("application/json") is False
    assert DipClient._is_html_content_type("application/json; charset=utf-8") is False


def test_is_html_content_type_handles_none():
    assert DipClient._is_html_content_type(None) is False


def test_dip_maintenance_error_is_subclass_of_dip_fetch_error():
    assert issubclass(DipMaintenanceError, DipFetchError)


@pytest.mark.asyncio
async def test_token_timeout_reports_safe_page_flags_without_url_values(caplog):
    page = _mock_page(
        wait_for_function_error=PlaywrightTimeoutError("Timeout 30000ms exceeded")
    )
    page.url = (
        "https://dip.cezdistribuce.cz/irj/portal/prehled-om"
        "?ean=SECRET_EAN&token=SECRET_TOKEN"
    )
    page.goto.return_value = Mock(status=200)
    page.evaluate.side_effect = None
    page.evaluate.return_value = {
        "ready": "complete",
        "login": False,
        "sessionToken": True,
    }
    context = _mock_context(page)

    with pytest.raises(DipTokenError) as exc_info:
        await DipClient().fetch_hdo(context, ean="SECRET_EAN")

    message = str(exc_info.value)
    assert "route=dip-signals-page" in message
    assert "navigation_http=200" in message
    assert "ready=complete" in message
    assert "login_form=false" in message
    assert "session_storage_has_token=true" in message
    assert "SECRET_EAN" not in message
    assert "SECRET_TOKEN" not in message
    assert "https://" not in message
    assert exc_info.value.__suppress_context__ is True
    assert "HDO token acquisition failed" in caplog.text
    assert "route=dip-signals-page" in caplog.text
    assert "SECRET_EAN" not in caplog.text
    assert "SECRET_TOKEN" not in caplog.text
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_safe_hdo_diagnostics_never_expose_redirect_url():
    page = Mock()
    page.url = "https://login.example.net/sso?code=DO_NOT_LOG"
    page.evaluate = AsyncMock(
        return_value={"ready": "interactive", "login": True, "sessionToken": False}
    )
    result = await _safe_token_diagnostics(page, Mock(status=302))
    assert "route=other-origin" in result
    assert "navigation_http=302" in result
    assert "login_form=true" in result
    assert "DO_NOT_LOG" not in result
    assert "login.example" not in result


@pytest.mark.asyncio
async def test_safe_hdo_diagnostics_discard_unexpected_page_values():
    page = Mock()
    page.url = "https://dip.cezdistribuce.cz/irj/portal/user/PRIVATE_IDENTIFIER"
    page.evaluate = AsyncMock(
        return_value={
            "ready": "SECRET_READY",
            "login": "SENSITIVE",
            "sessionToken": "SENSITIVE",
        }
    )
    result = await _safe_token_diagnostics(page, Mock(status="SECRET_STATUS"))
    assert "route=dip-other-portal-page" in result
    assert "navigation_http=unavailable" in result
    assert "ready=unavailable" in result
    assert "login_form=unavailable" in result
    assert "session_storage_has_token=unavailable" in result
    assert "PRIVATE" not in result
    assert "SENSITIVE" not in result


@pytest.mark.asyncio
async def test_safe_hdo_diagnostics_discard_exception_detail():
    page = Mock()
    page.url = "https://dip.cezdistribuce.cz/irj/portal/prehled-om?code=NEVER_LOG"
    page.evaluate = AsyncMock(side_effect=RuntimeError("PASSWORD=never_log"))
    result = await _safe_token_diagnostics(page, None)
    assert "navigation_http=unavailable" in result
    assert "ready=unavailable" in result
    assert "PASSWORD" not in result
    assert "NEVER_LOG" not in result


@pytest.mark.asyncio
async def test_hdo_timeout_diagnostic_does_not_fetch_signals():
    page = _mock_page(wait_for_function_error=PlaywrightTimeoutError("timeout"))
    page.url = "https://dip.cezdistribuce.cz/irj/portal/prehled-om"
    page.evaluate.side_effect = None
    page.evaluate.return_value = {
        "ready": "loading",
        "login": False,
        "sessionToken": False,
    }
    context = _mock_context(page)

    with pytest.raises(DipTokenError):
        await DipClient().fetch_hdo(context, ean="synthetic")

    assert page.evaluate.await_count == 2
    assert all(len(c.args) == 1 for c in page.evaluate.call_args_list)
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_hdo_browser_exception_is_redacted():
    private = "SYNTHETIC_PRIVATE_EAN_OR_TOKEN"
    page = _mock_page(evaluate_error=RuntimeError(private))
    context = _mock_context(page)

    with pytest.raises(DipTokenError, match="Token bootstrap failed") as error:
        await DipClient().fetch_hdo(context, ean="synthetic")

    assert private not in str(error.value)
    assert error.value.__suppress_context__ is True
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_hdo_untrusted_status_is_not_interpolated_into_error():
    private = "SYNTHETIC_UNTRUSTED_STATUS"
    page = _mock_page(
        fetch_result={"status": private, "contentType": "text/html", "body": private}
    )
    context = _mock_context(page)

    with pytest.raises(DipFetchError, match="invalid HTTP status") as error:
        await DipClient().fetch_hdo(context, ean="synthetic")

    assert private not in str(error.value)
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_hdo_invalid_json_is_redacted():
    private = "SYNTHETIC_PRIVATE_RESPONSE"
    page = _mock_page(
        fetch_result={
            "status": 200,
            "contentType": "application/json",
            "body": "not-json " + private,
        }
    )
    context = _mock_context(page)

    with pytest.raises(DipFetchError, match="Fetch failed:") as error:
        await DipClient().fetch_hdo(context, ean="synthetic")

    assert private not in str(error.value)
    page.close.assert_awaited_once()
