"""Allowlisted classification of CEZ PND error responses.

Never return response bodies, full headers, URLs, cookies, or parse exceptions.
This module does not log and makes no network requests.
"""

from __future__ import annotations

from typing import Any


REJECTION_STATUS_CODES = frozenset({403, 429})
REJECTION_COOLDOWN_SECONDS = 12 * 3600


def safe_content_kind(value: Any) -> str:
    """Classify untrusted Content-Type without exposing its original value."""
    if not isinstance(value, str):
        return "unknown"
    mime = value.split(";", 1)[0].strip().lower()
    if mime == "application/json" or mime.endswith("+json"):
        return "json"
    if mime in ("text/html", "application/xhtml+xml"):
        return "html"
    return "other"


def safe_html_category(body: Any) -> str:
    """Classify portal HTML using fixed labels only; never leak text."""
    if not isinstance(body, str):
        return "unknown"
    # Inspect a bounded prefix; preserve only a fixed categorical label.
    text = body[:65536].casefold()
    if any(marker in text for marker in (
        "the requested url was rejected", "request rejected", "access denied",
        "captcha", "checking your browser",
    )):
        return "portal-rejection"
    if any(marker in text for marker in (
        'name="username"', "name='username'", 'type="password"',
    )):
        return "login-page"
    if "odstávka" in text or "odstavka" in text:
        return "maintenance"
    return "other-html"
