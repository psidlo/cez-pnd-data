"""Main entry point for CEZ PND Home Assistant Add-on.

Reads configuration from environment variables and starts the orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt_client

from .auth import DEFAULT_USER_AGENT, PND_BASE_URL, PlaywrightAuthClient
from .dip_client import DipClient
from .mqtt_publisher import MqttPublisher
from .pnd_response_safety import (
    REJECTION_COOLDOWN_SECONDS,
    REJECTION_STATUS_CODES,
    safe_content_kind,
    safe_html_category,
)
from .orchestrator import Orchestrator, OrchestratorConfig, SessionExpiredError
from .session_manager import CredentialsProvider, SessionStore

PND_DATA_URL = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"


class PndFetchError(Exception):
    """Raised when PND data fetch fails (non-200 response, network error, etc.)."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PndRequestRejected(PndFetchError):
    """CEZ PND rejected a request; temporarily avoid further requests."""


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _get_async_playwright():  # type: ignore[no-untyped-def]
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]

    return async_playwright


def build_pnd_payload(
    assembly_id: int,
    date_from: str,
    date_to: str,
    electrometer_id: Optional[str],
) -> Dict[str, Any]:
    return {
        "format": "table",
        "idAssembly": assembly_id,
        "idDeviceSet": None,
        "intervalFrom": date_from,
        "intervalTo": date_to,
        "compareFrom": None,
        "opmId": None,
        "electrometerId": electrometer_id if electrometer_id is not None else "",
    }


class PndFetcher:
    def __init__(self, electrometer_id: Optional[str] = None) -> None:
        self._electrometer_id = electrometer_id
        self._blocked_until_monotonic = 0.0

    @property
    def cooldown_seconds_remaining(self) -> float:
        """Remaining in-process cooldown; do not share raw identifiers."""
        return max(0.0, self._blocked_until_monotonic - time.monotonic())

    def _begin_rejection_backoff(self) -> None:
        self._blocked_until_monotonic = max(
            self._blocked_until_monotonic,
            time.monotonic() + REJECTION_COOLDOWN_SECONDS,
        )
        logger.warning("PND request rejected; pausing PND requests for 12 hours")

    def _check_rejection_backoff(self) -> None:
        if self.cooldown_seconds_remaining > 0:
            raise PndRequestRejected("PND rejection cooldown active")

    @staticmethod
    async def _create_browser_context(browser: Any) -> Any:
        return await browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            locale="cs-CZ",
            timezone_id="Europe/Prague",
            viewport={"width": 1280, "height": 720},
        )

    async def fetch(
        self,
        cookies: list,
        *,
        assembly_id: int,
        date_from: str,
        date_to: str,
        electrometer_id: str | None = None,
    ) -> Dict[str, Any]:
        self._check_rejection_backoff()
        async_playwright = _get_async_playwright()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await self._create_browser_context(browser)
            try:
                await context.add_cookies(cookies)

                # Navigate to PND dashboard to establish WAF fingerprint (same as live_verify_flow.py)
                logger.debug("Navigating to PND dashboard for WAF fingerprint...")
                try:
                    page = await context.new_page()
                    await page.goto(
                        "https://pnd.cezdistribuce.cz/cezpnd2/dashboard/view",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    await page.close()
                    await asyncio.sleep(3)
                except Exception as e:
                    logger.debug("PND dashboard navigation failed (details suppressed)")

                effective_electrometer_id = electrometer_id or self._electrometer_id

                payload = build_pnd_payload(
                    assembly_id,
                    date_from,
                    date_to,
                    effective_electrometer_id,
                )
                form_payload = {k: ("" if v is None else v) for k, v in payload.items()}

                # WAF warmup: Send JSON request first (will fail with 400, but sets WAF cookies/state)
                logger.debug("WAF warmup (JSON request)...")
                try:
                    warmup_response = await context.request.post(
                        PND_DATA_URL,
                        data=json.dumps(form_payload),
                        headers={"Content-Type": "application/json"},
                    )
                    logger.debug(
                        "Warmup status: %d (expected 400)", warmup_response.status
                    )
                except Exception as e:
                    logger.debug("Warmup failed (details suppressed)")

                await asyncio.sleep(1)

                return await self._fetch_one_in_context(
                    context, effective_electrometer_id, assembly_id, date_from, date_to
                )
            finally:
                await context.close()
                await browser.close()

    async def fetch_all(
        self,
        cookies: list,
        meter_id: str,
        assembly_configs: list,
    ) -> Dict[str, Any]:
        """Fetch all assemblies in a single browser context per cycle.

        Creates ONE Playwright browser for all assemblies. Navigates to PND base
        URL first to establish WAF state, then does a single WAF warmup POST before
        iterating through all assembly fetches in the same context.

        Handles Tab 17 (daily_registers) yesterday-fallback internally.

        Returns a dict mapping assembly name → payload for assemblies with data.
        """
        from datetime import datetime, timedelta

        self._check_rejection_backoff()
        today = datetime.now()
        date_from = today.strftime("%d.%m.%Y 00:00")
        date_to = today.strftime("%d.%m.%Y 23:59")

        async_playwright = _get_async_playwright()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await self._create_browser_context(browser)
            try:
                await context.add_cookies(cookies)

                # Navigate to PND base URL to establish browser history / WAF fingerprint
                logger.debug("Navigating to PND base URL for WAF fingerprint...")
                try:
                    page = await context.new_page()
                    await page.goto(
                        PND_BASE_URL, wait_until="domcontentloaded", timeout=30_000
                    )
                    await page.close()
                except Exception as e:
                    logger.debug("PND navigation warmup failed (details suppressed)")

                # Single WAF warmup POST using the first assembly
                first_config = assembly_configs[0]
                warmup_payload = build_pnd_payload(
                    first_config["id"],
                    date_from,
                    date_to,
                    meter_id,
                )
                logger.debug("WAF warmup (JSON request for all assemblies)...")
                try:
                    warmup_response = await context.request.post(
                        PND_DATA_URL,
                        data=json.dumps(warmup_payload),
                        headers={"Content-Type": "application/json"},
                    )
                    logger.debug(
                        "Warmup status: %d (expected 400)", warmup_response.status
                    )
                except Exception as e:
                    logger.debug("Warmup POST failed (details suppressed)")

                await asyncio.sleep(1)

                results: Dict[str, Any] = {}

                for config in assembly_configs:
                    assembly_id: int = config["id"]
                    assembly_name: str = config["name"]

                    try:
                        payload = await self._fetch_one_in_context(
                            context, meter_id, assembly_id, date_from, date_to
                        )
                    except PndRequestRejected:
                        raise  # Do not request further assemblies after rejection.
                    except Exception:
                        logger.error(
                            "Assembly %s failed (details suppressed) — continuing",
                            assembly_name,
                        )
                        continue

                    if config.get("fallback_yesterday") and not payload.get(
                        "hasData", True
                    ):
                        logger.warning(
                            "Assembly %s has no data for today, retrying yesterday",
                            assembly_name,
                        )
                        date_obj = today - timedelta(days=1)
                        yesterday_from = date_obj.strftime("%d.%m.%Y 00:00")
                        try:
                            payload = await self._fetch_one_in_context(
                                context,
                                meter_id,
                                assembly_id,
                                yesterday_from,
                                date_from,
                            )
                        except PndRequestRejected:
                            raise
                        except Exception:
                            logger.error(
                                "Assembly %s yesterday-fallback failed "
                                "(details suppressed)",
                                assembly_name,
                            )
                            continue

                    if payload and payload.get("hasData"):
                        results[assembly_name] = payload
                    else:
                        logger.warning(
                            "Assembly %s has no data for meter %s",
                            assembly_name,
                            meter_id,
                        )

                return results

            finally:
                await context.close()
                await browser.close()

    async def _fetch_one_in_context(
        self,
        context: Any,
        meter_id: Optional[str],
        assembly_id: int,
        date_from: str,
        date_to: str,
    ) -> Dict[str, Any]:
        payload = build_pnd_payload(assembly_id, date_from, date_to, meter_id)
        form_payload = {k: ("" if v is None else v) for k, v in payload.items()}

        self._check_rejection_backoff()
        response = await context.request.post(PND_DATA_URL, data=form_payload)
        status = response.status
        if type(status) is not int or not (100 <= status <= 599):
            raise PndFetchError("PND response has invalid HTTP status")
        if status in (302, 401):
            raise SessionExpiredError(f"PND session expired (HTTP {status})")
        if status in REJECTION_STATUS_CODES:
            self._begin_rejection_backoff()
            raise PndRequestRejected(
                f"PND portal rejected request (HTTP {status})",
                status_code=status,
            )
        if status != 200:
            raise PndFetchError(
                f"PND fetch failed with status {status}", status_code=status
            )

        headers = response.headers or {}
        content_type = headers.get("content-type") if hasattr(headers, "get") else None
        kind = safe_content_kind(content_type)
        if kind != "json":
            category = "not-html"
            if kind == "html":
                try:
                    category = safe_html_category(await response.text())
                except Exception:
                    category = "unknown"
                if category == "portal-rejection":
                    self._begin_rejection_backoff()
                    raise PndRequestRejected(
                        "PND portal rejected request (HTML response)",
                        status_code=status,
                    )
                if category == "login-page":
                    raise SessionExpiredError("PND fetch returned login page")
            logger.warning(
                "PND fetch returned non-JSON response (kind=%s, category=%s)",
                kind,
                category,
            )
            raise PndFetchError(
                f"PND fetch returned non-JSON response "
                f"(kind={kind}, category={category})",
                status_code=status,
            )

        try:
            data: Dict[str, Any] = await response.json()
        except Exception:
            logger.warning("PND fetch JSON parse failed (details suppressed)")
            raise PndFetchError(
                "PND fetch JSON parse failed", status_code=status
            ) from None
        if not isinstance(data, dict):
            raise PndFetchError(
                "PND JSON response is not an object", status_code=status
            )
        indicator = data.get("hasData")
        safe_indicator = (
            "true" if indicator is True else "false" if indicator is False
            else "unknown"
        )
        logger.debug(
            "PND fetch assembly=%d status=%d hasData=%s",
            assembly_id,
            status,
            safe_indicator,
        )
        return data


class MQTTClientWrapper:
    """Wrapper for paho.mqtt.client to match expected interface."""

    def __init__(self, host: str, port: int, username: str, password: str):
        callback_api_version = getattr(mqtt_client, "CallbackAPIVersion").VERSION2
        self._client = mqtt_client.Client(callback_api_version=callback_api_version)
        self._client.username_pw_set(username, password)
        self._host = host
        self._port = port

    def will_set(self, topic: str, payload: str, qos: int = 1, retain: bool = True):
        """Set Last Will and Testament."""
        self._client.will_set(topic, payload, qos, retain)

    def connect(self):
        """Connect to MQTT broker."""
        self._client.connect(self._host, self._port, 60)

    def publish(self, topic: str, payload: str, qos: int = 1, retain: bool = True):
        """Publish a message to MQTT broker."""
        self._client.publish(topic, payload, qos, retain)

    def disconnect(self):
        """Disconnect from MQTT broker."""
        self._client.disconnect()


def validate_electrometers_config(
    electrometers_json: Optional[str],
) -> List[Dict[str, str]]:
    if not electrometers_json:
        return []

    try:
        electrometers = json.loads(electrometers_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in electrometers configuration: {e}")

    if not isinstance(electrometers, list):
        raise ValueError("Electrometers configuration must be a JSON array")

    seen_electrometer_ids = set()
    seen_eans = set()

    for i, electrometer in enumerate(electrometers):
        if not isinstance(electrometer, dict):
            raise ValueError(f"Electrometer {i} must be an object")

        if "electrometer_id" not in electrometer:
            raise ValueError(
                f"Electrometer {i} missing required field 'electrometer_id'"
            )
        if "ean" not in electrometer:
            raise ValueError(f"Electrometer {i} missing required field 'ean'")

        electrometer_id = electrometer["electrometer_id"]
        ean = electrometer["ean"]

        if not isinstance(electrometer_id, str) or not electrometer_id.strip():
            raise ValueError(f"Electrometer {i} has empty or invalid 'electrometer_id'")
        if not isinstance(ean, str) or not ean.strip():
            raise ValueError(f"Electrometer {i} has empty or invalid 'ean'")

        if electrometer_id in seen_electrometer_ids:
            raise ValueError(f"Duplicate electrometer_id: {electrometer_id}")
        if ean in seen_eans:
            raise ValueError(f"Duplicate ean: {ean}")

        seen_electrometer_ids.add(electrometer_id)
        seen_eans.add(ean)

    return electrometers


def read_env_var(name: str, required: bool = True) -> Optional[str]:
    """Read environment variable with validation."""
    value = os.getenv(name)
    if required and not value:
        logger.error(f"Required environment variable {name} is not set")
        sys.exit(1)
    return value


def create_config() -> Dict[str, Dict[str, Any]]:
    """Create configuration dictionary from environment variables."""
    config: Dict[str, Dict[str, Any]] = {
        "cez": {
            "email": read_env_var("CEZ_EMAIL"),
            "password": read_env_var("CEZ_PASSWORD"),
            "electrometer_id": read_env_var("CEZ_ELECTROMETER_ID", required=False)
            or "auto",
            "ean": read_env_var("CEZ_EAN", required=False) or "",
        },
        "mqtt": {
            "host": read_env_var("MQTT_HOST"),
            "port": int(read_env_var("MQTT_PORT", required=False) or "1883"),
            "username": read_env_var("MQTT_USER", required=False) or "",
            "password": read_env_var("MQTT_PASSWORD", required=False) or "",
        },
    }

    electrometers_json = read_env_var("CEZ_ELECTROMETERS", required=False)
    try:
        electrometers = validate_electrometers_config(electrometers_json)

        # If CEZ_ELECTROMETERS is provided, use it as the canonical list
        if electrometers:
            config["cez"]["electrometers"] = electrometers
        else:
            # Fall back to single electrometer_id/ean pair for backward compatibility
            electrometer_id = read_env_var("CEZ_ELECTROMETER_ID", required=False)
            ean = read_env_var("CEZ_EAN", required=False)

            if electrometer_id and ean:
                config["cez"]["electrometers"] = [
                    {"electrometer_id": electrometer_id, "ean": ean}
                ]
            elif electrometer_id:
                # Only electrometer_id provided, ean will be empty
                config["cez"]["electrometers"] = [
                    {"electrometer_id": electrometer_id, "ean": ""}
                ]
            else:
                # No electrometers configured - this should fail validation elsewhere
                config["cez"]["electrometers"] = []

    except ValueError as e:
        logger.error(f"Invalid electrometers configuration: {e}")
        sys.exit(1)

    if config["cez"]["electrometer_id"] == "auto":
        config["cez"]["electrometer_id"] = None

    return config


async def main():
    """Main application entry point."""
    # Read configuration
    config = create_config()

    # Log configuration (excluding password)
    logger.info("Starting CEZ PND add-on")
    logger.info(f"Email: {config['cez']['email']}")
    logger.info(f"Electrometer ID: {config['cez']['electrometer_id'] or 'auto-detect'}")

    # Log canonical electrometers list structure
    if config["cez"].get("electrometers"):
        electrometers = config["cez"]["electrometers"]
        logger.info(f"Configured electrometers: {len(electrometers)}")
        for i, electrometer in enumerate(electrometers, 1):
            raw_ean = electrometer.get("ean", "")
            if raw_ean and len(raw_ean) > 4:
                ean_display = "*" * (len(raw_ean) - 4) + raw_ean[-4:]
            else:
                ean_display = "empty" if not raw_ean else raw_ean
            logger.info(
                f"  {i}. electrometer_id: {electrometer['electrometer_id']}, ean: {ean_display}"
            )
    else:
        logger.warning("No electrometers configured - this may cause runtime errors")

    logger.info(f"MQTT Host: {config['mqtt']['host']}:{config['mqtt']['port']}")

    # Create MQTT client
    mqtt_client = MQTTClientWrapper(
        host=config["mqtt"]["host"],
        port=config["mqtt"]["port"],
        username=config["mqtt"]["username"],
        password=config["mqtt"]["password"],
    )

    # Create orchestrator components
    credentials_provider = CredentialsProvider()
    session_store = SessionStore()

    auth_client = PlaywrightAuthClient(
        credentials_provider=credentials_provider, session_store=session_store
    )

    # These will be replaced inside the async with block
    pnd_fetcher = None
    hdo_fetcher = None

    mqtt_publisher = MqttPublisher(
        mqtt_client,
        electrometers=config["cez"]["electrometers"],
    )

    # Create orchestrator configuration
    orchestrator_config = OrchestratorConfig(
        electrometers=config["cez"]["electrometers"],
        email=config["cez"]["email"],
        poll_interval_seconds=900,  # 15 minutes
    )

    async def run_orchestrator_with_session():
        nonlocal pnd_fetcher, hdo_fetcher

        pnd_fetcher = PndFetcher().fetch
        hdo_fetcher = DipClient().fetch_hdo

        orchestrator = Orchestrator(
            config=orchestrator_config,
            auth_client=auth_client,
            fetcher=pnd_fetcher,
            mqtt_publisher=mqtt_publisher,
            hdo_fetcher=hdo_fetcher,
        )

        await orchestrator.run_loop()

    # Set up signal handlers for graceful shutdown
    _ = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def signal_handler(signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        _ = await run_orchestrator_with_session()
    except asyncio.CancelledError:
        logger.info("Orchestrator cancelled")
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        # Clean shutdown
        logger.info("Shutting down...")
        await auth_client.close()
        mqtt_publisher.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
