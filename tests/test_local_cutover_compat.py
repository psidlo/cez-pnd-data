"""Behavioral regressions found while preparing the local 0.4.8 cutover."""

import asyncio
import subprocess
import sys
import textwrap

import pytest

from addon.src.main import _run_until_shutdown
from addon.src.parser import CezDataParser


def test_empty_final_interval_preserves_each_last_known_mqtt_value():
    payload = {
        "hasData": True,
        "columns": [
            {"id": "0", "name": "Datum", "unit": None},
            {"id": "1", "name": "+A/111111", "unit": "kW"},
            {"id": "2", "name": "-A/111111", "unit": "kW"},
            {"id": "3", "name": "Rv/111111", "unit": "kW"},
        ],
        "values": [
            {
                "0": {"v": "16.11.2026 23:30"},
                "1": {"v": "1,25"},
                "2": {"v": "0,5"},
                "3": {"v": "0"},
            },
            {
                "0": {"v": "16.11.2026 23:45"},
                "1": {"v": None},
                "2": {"v": "0,25"},
                "3": {"v": None},
            },
            {
                "0": {"v": "16.11.2026 23:59"},
                "1": {"v": None},
                "2": {"v": None},
                "3": {"v": None},
            },
        ],
    }
    parser = CezDataParser(payload)
    result = parser.get_latest_reading_dict()
    assert result["consumption_kw"] == 1.25
    assert result["production_kw"] == 0.25
    assert result["reactive_kw"] == 0.0
    # The actual records must still show missing data, not carry-forward values.
    assert parser.parse_records()[-1].consumption_kw is None
    assert parser.parse_records()[-1].production_kw is None
    assert result["daily_consumption_kwh"] is None


@pytest.mark.asyncio
async def test_shutdown_cancels_live_poll_and_runs_worker_cleanup():
    started, cleanup, stop = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def worker():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup.set()

    task = asyncio.create_task(_run_until_shutdown(worker(), stop))
    await asyncio.wait_for(started.wait(), timeout=1)
    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert cleanup.is_set()


@pytest.mark.asyncio
async def test_poll_failure_propagates_instead_of_waiting_forever():
    async def worker():
        raise RuntimeError("synthetic poll failure")

    with pytest.raises(RuntimeError, match="synthetic poll failure"):
        await asyncio.wait_for(
            _run_until_shutdown(worker(), asyncio.Event()), timeout=1
        )


@pytest.mark.asyncio
async def test_external_cancellation_also_cleans_up_poll_task():
    started, cleanup = asyncio.Event(), asyncio.Event()

    async def worker():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup.set()

    task = asyncio.create_task(_run_until_shutdown(worker(), asyncio.Event()))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleanup.is_set()


@pytest.mark.skipif(sys.platform == "win32", reason="Production uses POSIX SIGTERM")
def test_real_sigterm_wakes_idle_main_and_completes_cleanup():
    """The signal must wake a selector with no active I/O or poll timer."""
    program = textwrap.dedent("""
        import asyncio
        import os
        import signal
        import threading
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        import addon.src.main as app

        config = {
            "cez": {"electrometers": [], "email": "synthetic@example.invalid"},
            "mqtt": {"host": "unused", "port": 1883, "username": "", "password": ""},
        }
        app.create_config = lambda: config
        app.archive_settings_from_env = lambda env: (False, None, 1)
        app.log_startup_summary = lambda config: None
        app.MQTTClientWrapper = MagicMock()
        app.CredentialsProvider = MagicMock()
        app.SessionStore = MagicMock()
        auth = SimpleNamespace(close=AsyncMock())
        publisher = SimpleNamespace(stop=MagicMock())
        app.PlaywrightAuthClient = MagicMock(return_value=auth)
        app.MqttPublisher = MagicMock(return_value=publisher)

        async def idle_poll():
            threading.Timer(
                0.2, lambda: os.kill(os.getpid(), signal.SIGTERM)
            ).start()
            await asyncio.Event().wait()

        app.Orchestrator = MagicMock(
            return_value=SimpleNamespace(run_loop=idle_poll)
        )
        asyncio.run(app.main())
        auth.close.assert_awaited_once()
        publisher.stop.assert_called_once()
        print("cleanup-complete")
        """)
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    assert "cleanup-complete" in result.stdout
