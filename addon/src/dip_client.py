from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

DIP_PORTAL_URL = "https://dip.cezdistribuce.cz/irj/portal"
SIGNALS_PATH_TEMPLATE = "prehled-om?path=supply-point-detail/signals/{ean}"


class DipTokenError(Exception):
    """Raised when token acquisition fails."""


class DipFetchError(Exception):
    """Raised when HDO signals fetch fails."""


class DipMaintenanceError(DipFetchError):
    """Raised when DIP endpoint is temporarily unavailable (maintenance)."""


def _location_category(url: Any) -> str:
    """Never put a redirect URL (query, path identifiers) into error output."""
    if not isinstance(url, str):
        return "unavailable"
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https":
            return "other-origin"
        if parsed.hostname == "dip.cezdistribuce.cz":
            if parsed.path.rstrip("/") == "/irj/portal/prehled-om":
                return "dip-signals-page"
            if parsed.path.startswith("/irj/portal"):
                return "dip-other-portal-page"
            return "dip-other-page"
        if parsed.hostname == "pnd.cezdistribuce.cz":
            return "pnd-page"
        return "other-origin"
    except ValueError:
        return "unavailable"


async def _safe_token_diagnostics(page: Any, navigation_response: Any) -> str:
    """Only return allowlisted diagnostic categories; no URLs or page values."""
    route = _location_category(getattr(page, "url", None))
    status = getattr(navigation_response, "status", None)
    http = (
        str(status)
        if type(status) is int and 100 <= status <= 599
        else "unavailable"
    )
    ready, login, session_token = "unavailable", "unavailable", "unavailable"
    try:
        result = await asyncio.wait_for(
            page.evaluate(
                """() => ({
                  ready: document.readyState,
                  login: Boolean(document.querySelector('input[name="username"]')),
                  sessionToken: sessionStorage.getItem('dip-request-token') !== null
                })"""
            ),
            timeout=4,
        )
        if isinstance(result, dict):
            if result.get("ready") in ("loading", "interactive", "complete"):
                ready = result["ready"]
            if type(result.get("login")) is bool:
                login = str(result["login"]).lower()
            if type(result.get("sessionToken")) is bool:
                session_token = str(result["sessionToken"]).lower()
    except Exception:
        # Playwright errors can contain full URLs, so do not interpolate exc.
        pass
    return (f"route={route}, navigation_http={http}, ready={ready}, "
            f"login_form={login}, session_storage_has_token={session_token}")


class DipClient:
    """DIP API client for HDO tariff data."""

    DEFAULT_TIMEOUT = 30_000

    @staticmethod
    def _is_html_content_type(content_type: str | None) -> bool:
        return content_type is not None and "text/html" in content_type.lower()

    async def fetch_hdo(self, context: Any, ean: str) -> dict[str, Any]:
        page = await context.new_page()
        try:
            navigation_response = await page.goto(
                f"{DIP_PORTAL_URL}/prehled-om",
                wait_until="domcontentloaded",
                timeout=self.DEFAULT_TIMEOUT,
            )

            try:
                await page.wait_for_function(
                    "() => localStorage.getItem('dip-request-token') !== null",
                    timeout=self.DEFAULT_TIMEOUT,
                )
            except (TimeoutError, asyncio.TimeoutError, PlaywrightTimeoutError) as exc:
                diagnostics = await _safe_token_diagnostics(page, navigation_response)
                raise DipTokenError(
                    f"Token not found in localStorage ({diagnostics})"
                ) from exc

            token = await page.evaluate(
                "() => localStorage.getItem('dip-request-token')"
            )
            if not token:
                raise DipTokenError("Empty dip-request-token in localStorage")

            result = await page.evaluate(
                """async (args) => {
                const resp = await fetch(args.url, {
                    headers: {
                        'X-Request-Token': args.token,
                        'Accept': 'application/json, text/plain, */*'
                    }
                });
                const contentType = resp.headers.get('content-type') || '';
                const text = await resp.text();
                return { status: resp.status, contentType: contentType, body: text };
            }""",
                {
                    "url": f"{DIP_PORTAL_URL}/{SIGNALS_PATH_TEMPLATE.format(ean=ean)}",
                    "token": token,
                },
            )

            status = result["status"]
            content_type = result["contentType"]
            body = result["body"]

            if status in (400, 503):
                raise DipMaintenanceError(
                    f"Signals endpoint unavailable (HTTP {status})"
                )
            if status != 200:
                raise DipFetchError(f"Signals request failed: HTTP {status}")
            if self._is_html_content_type(content_type):
                raise DipMaintenanceError(
                    "Signals endpoint returned HTML (maintenance page)"
                )

            data = json.loads(body)
            if "data" not in data:
                raise DipFetchError("Data missing from response")
            return data["data"]

        except (DipTokenError, DipFetchError):
            raise
        except (asyncio.TimeoutError, Exception) as exc:
            raise DipFetchError(f"Fetch failed: {exc}") from exc
        finally:
            await page.close()
