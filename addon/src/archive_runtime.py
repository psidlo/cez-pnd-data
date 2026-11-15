"""Opt-in archive-cycle hook, isolated from the normal CEZ MQTT poll.

This module never publishes MQTT messages and never turns missing samples into
zero. Disabled installations must not construct ArchiveStore or touch SQLite.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from .archive import ArchiveStore
from .archive_backfill import ArchiveBackfill
from .orchestrator import ASSEMBLY_CONFIGS

LOGGER = logging.getLogger(__name__)


def archive_settings_from_env(env: dict[str, str]) -> tuple[bool, str, int]:
    enabled = str(env.get("CEZ_ARCHIVE_ENABLED", "false")).lower() in ("true", "1", "yes")
    if not enabled:
        return False, "", 0
    start_date = str(env.get("CEZ_ARCHIVE_START_DATE", ""))
    try:
        date.fromisoformat(start_date)
    except ValueError:
        raise ValueError("Archive requires a valid YYYY-MM-DD start date") from None
    try:
        max_days = int(env.get("CEZ_ARCHIVE_MAX_DAYS", "1"))
    except (ValueError, TypeError):
        raise ValueError("Archive max_days must be an integer") from None
    if not 1 <= max_days <= 62:
        raise ValueError("Archive max_days must be between 1 and 62")
    return True, start_date, max_days


class ArchiveCycle:
    """Bounded per-poll backfill, sharing the existing PND fetcher and session.

    One global request budget is shared across all configured meters. The
    existing meter EAN is treated as the import EAN; an unknown export EAN is
    left explicitly blank rather than guessed.
    """

    def __init__(
        self,
        fetcher: Any,
        *,
        start_date: str,
        max_days: int,
        rejection_error: type[Exception] | tuple[type[Exception], ...],
        store: ArchiveStore | None = None,
    ) -> None:
        self.store = store if store is not None else ArchiveStore()
        self._owns_store = store is None
        self.backfill = ArchiveBackfill(self.store)
        self.fetcher = fetcher
        self.start_date = start_date
        self.max_days = max_days
        self.rejection_error = rejection_error

    async def run(self, cookies: list[dict], meters: list[dict]) -> None:
        remaining = self.max_days
        for meter in meters:
            if remaining <= 0:
                break
            meter_id = meter.get("electrometer_id")
            import_ean = meter.get("ean")
            if not meter_id or not import_ean:
                LOGGER.warning("Archive skipped a meter without required configuration")
                continue
            result = await self.backfill.run(
                self.fetcher,
                cookies,
                str(meter_id),
                ASSEMBLY_CONFIGS,
                self.start_date,
                remaining,
                str(import_ean),
                "",  # Unknown export EAN is not inferred.
                rejection_error=self.rejection_error,
            )
            remaining -= result.attempted
            if result.paused_by_rejection:
                LOGGER.warning("Archive batch paused after PND portal rejection")
                break

    def close(self) -> None:
        if self._owns_store:
            self.store.close()
