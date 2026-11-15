"""Opt-in archive-cycle hook, isolated from the normal CEZ MQTT poll.

This module never publishes MQTT messages and never turns missing samples into
zero. Disabled installations must not construct ArchiveStore or touch SQLite.
"""
from __future__ import annotations

import json
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


def archive_meters_from_env(
    env: dict[str, str], mqtt_meters: list[dict]
) -> list[dict]:
    """Choose archival meters independently from MQTT discovery.

    The legacy add-on may publish one current meter while archiving older
    meters belonging to the same supply. No real EAN/ID defaults are stored.
    """
    raw = str(env.get("CEZ_ARCHIVE_METER_IDS", "[]"))
    try:
        identifiers = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("Archive meter list must be a JSON array") from None
    if not isinstance(identifiers, list) or len(identifiers) > 32 or any(
        not isinstance(value, str)
        or not value.isdecimal()
        or not value
        for value in identifiers
    ):
        raise ValueError("Archive meter list requires numeric ID strings") from None

    selected = list(dict.fromkeys(identifiers))
    if not selected:
        # Safe fallback only for configurations without a separate list.
        return list(mqtt_meters)

    imported = str(env.get("CEZ_IMPORT_EAN", "")).strip()
    exported = str(env.get("CEZ_EXPORT_EAN", "")).strip()
    if bool(imported) != bool(exported):
        raise ValueError("Archive EAN pair must be both set or both absent")
    meters = []
    for meter_id in selected:
        entry = {"electrometer_id": meter_id}
        if imported and exported:
            entry.update(
                archive_import_ean=imported, archive_export_ean=exported
            )
        meters.append(entry)
    return meters


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
            if not meter_id:
                LOGGER.warning("Archive skipped a meter without identifier")
                continue
            stored = self.store.db.execute(
                "SELECT import_ean, export_ean FROM meter_metadata WHERE meter_id=?",
                (str(meter_id),),
            ).fetchone()
            explicit_import = meter.get("archive_import_ean")
            explicit_export = meter.get("archive_export_ean")
            if stored and all(isinstance(v, str) and v.strip() for v in stored):
                import_ean, export_ean = stored
                if (
                    (explicit_import is not None and explicit_import != import_ean)
                    or (explicit_export is not None and explicit_export != export_ean)
                ):
                    LOGGER.warning("Archive EAN metadata conflict; skipping meter")
                    continue
            elif (
                isinstance(explicit_import, str) and explicit_import.strip()
                and isinstance(explicit_export, str) and explicit_export.strip()
            ):
                import_ean, export_ean = explicit_import, explicit_export
            else:
                # The generic 'ean' is a supply identifier, not necessarily an
                # import/export EAN. Never overwrite stored metadata with guesses.
                LOGGER.warning("Archive requires explicit import/export EAN metadata")
                continue
            result = await self.backfill.run(
                self.fetcher,
                cookies,
                str(meter_id),
                ASSEMBLY_CONFIGS,
                self.start_date,
                remaining,
                str(import_ean),
                str(export_ean),
                rejection_error=self.rejection_error,
            )
            remaining -= result.attempted
            if result.paused_by_rejection:
                LOGGER.warning("Archive batch paused after PND portal rejection")
                break

    def close(self) -> None:
        if self._owns_store:
            self.store.close()
