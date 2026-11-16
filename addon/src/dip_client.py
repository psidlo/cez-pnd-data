from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import quote, urlsplit

logger = logging.getLogger(__name__)

DIP_PORTAL_URL = "https://dip.cezdistribuce.cz/irj/portal"
SIGNALS_PATH_TEMPLATE = "prehled-om?path=supply-point-detail/signals/{ean}"


# The portal's AuthService refreshes /rest-auth-api?path=/token/get and its
# HTTP interceptor unwraps response.data before storing dip-request-token.
# Keep both requests in the authenticated browser page; never use anonymous
# tokens, export the browser session, or persist a token in logs/files.
TOKEN_BOOTSTRAP_JS = r"""async () => {
    if (window.location.origin !== 'https://dip.cezdistribuce.cz') {
        return {failure: 'other-origin'};
    }
    const valid = value => typeof value === 'string' && value.trim().length > 0
        && !['null', 'undefined', '[object Object]'].includes(value);
    try {
        const stored = localStorage.getItem('dip-request-token');
        if (valid(stored)) return stored;
    } catch (_) { /* Storage restrictions must not prevent API bootstrap. */ }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
        const response = await fetch('/irj/portal/rest-auth-api?path=/token/get', {
            credentials: 'same-origin', redirect: 'error', cache: 'no-store',
            headers: {'Accept': 'application/json, text/plain, */*'},
            signal: controller.signal
        });
        if ([400, 503].includes(response.status)) return {failure: 'maintenance'};
        if (response.status !== 200) return {failure: 'http-error'};
        const contentType = response.headers.get('content-type') || '';
        if (!contentType.toLowerCase().includes('application/json')) {
            return {failure: 'non-json'};
        }
        const body = await response.json();
        // Current DIP wraps its JSON string in {data: ...}. Accept the older
        // direct-string / {token: ...} forms without stringifying objects.
        const token = typeof body === 'string' ? body
            : (body && typeof body === 'object' ? (body.data ?? body.token) : null);
        return valid(token) ? token : {failure: 'invalid-token'};
    } catch (_) {
        return {failure: 'request-failed'};
    } finally {
        clearTimeout(timer);
    }
}"""


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
        str(status) if type(status) is int and 100 <= status <= 599 else "unavailable"
    )
    ready, login, session_token = "unavailable", "unavailable", "unavailable"
    try:
        result = await asyncio.wait_for(
            page.evaluate("""() => ({
                  ready: document.readyState,
                  login: Boolean(document.querySelector('input[name="username"]')),
                  sessionToken: sessionStorage.getItem('dip-request-token') !== null
                })"""),
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
    return (
        f"route={route}, navigation_http={http}, ready={ready}, "
        f"login_form={login}, session_storage_has_token={session_token}"
    )


class DipClient:
    """DIP API client for HDO tariff data."""

    DEFAULT_TIMEOUT = 30_000

    @staticmethod
    def _is_html_content_type(content_type: str | None) -> bool:
        return content_type is not None and "text/html" in content_type.lower()

    async def _request_token(self, page: Any, navigation_response: Any) -> str:
        """Bootstrap the DIP token explicitly, without waiting for Angular."""
        try:
            result = await page.evaluate(TOKEN_BOOTSTRAP_JS)
        except Exception:
            result = None
        if (
            isinstance(result, str)
            and result.strip()
            and result not in ("null", "undefined", "[object Object]")
        ):
            return result
        if isinstance(result, dict) and result.get("failure") == "maintenance":
            raise DipMaintenanceError("Token endpoint unavailable") from None
        diagnostics = await _safe_token_diagnostics(page, navigation_response)
        logger.warning("HDO token acquisition failed (%s)", diagnostics)
        raise DipTokenError(f"Token bootstrap failed ({diagnostics})") from None

    async def fetch_hdo(self, context: Any, ean: str) -> dict[str, Any]:
        page = await context.new_page()
        try:
            navigation_response = await page.goto(
                f"{DIP_PORTAL_URL}/prehled-om",
                wait_until="domcontentloaded",
                timeout=self.DEFAULT_TIMEOUT,
            )

            token = await self._request_token(page, navigation_response)

            signals_url = f"{DIP_PORTAL_URL}/" + SIGNALS_PATH_TEMPLATE.format(
                ean=quote(ean, safe="")
            )
            result = await page.evaluate(
                """async (args) => {
                const resp = await fetch(args.url, {
                    credentials: 'same-origin', redirect: 'error', cache: 'no-store',
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
                    "url": signals_url,
                    "token": token,
                },
            )

            status = result["status"]
            if type(status) is not int or not 100 <= status <= 599:
                raise DipFetchError("Signals endpoint returned invalid HTTP status")
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
        except Exception:
            # Browser errors may contain URLs, EANs or authentication tokens.
            # Preserve the exception type without exposing untrusted details.
            raise DipFetchError("Fetch failed: details suppressed") from None
        finally:
            await page.close()
