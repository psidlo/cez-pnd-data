"""Optional CEZ PND archive backfill, independent of Home Assistant and MQTT.

Network access is delegated to a caller-provided fetcher. Neither the archive
nor its backfill ever treats missing measurements as zero.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .archive import ArchiveStore, _last_profile_ok

LOGGER = logging.getLogger(__name__)
PROFILE_ASSEMBLY_ID = -1003
MAX_DAYS_PER_CYCLE = 62
MIN_RETRY_INTERVAL = timedelta(hours=2)
EMPTY_RETRY_INTERVAL = timedelta(days=7)


@dataclass(frozen=True)
class BackfillTask:
    day: date
    assemblies: tuple[dict, ...]
    repair_only: bool


@dataclass(frozen=True)
class BackfillResult:
    planned: int = 0
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    paused_by_rejection: bool = False


class ArchiveBackfill:
    """Select and fetch a bounded number of historical days safely.

    Depends only on the storage interface from ``ArchiveStore``. The caller
    supplies a working fetcher, credentials, and an explicit rejection type.
    """

    def __init__(
        self, store: ArchiveStore, *, now: Callable[[], datetime] | None = None
    ) -> None:
        self.store = store
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _clock(self) -> tuple[datetime, date]:
        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Backfill clock must be timezone aware")
        now = now.astimezone(timezone.utc)
        try:
            today = now.astimezone(ZoneInfo("Europe/Prague")).date()
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError("Europe/Prague time zone data is required") from exc
        return now, today

    @staticmethod
    def _attempt_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            instant = datetime.fromisoformat(value)
        except ValueError:
            return None
        if instant.tzinfo is None:
            # Historic archive uses UTC; older rows might lack an offset.
            instant = instant.replace(tzinfo=timezone.utc)
        return instant.astimezone(timezone.utc)

    def incomplete_final_days(self, meter_id: str) -> set[str]:
        """Retry missing final intervals only if another same-EAN meter lacks it.

        Inactive/replaced meters must not be queried indefinitely when a
        different meter for that *same supply* holds the final interval.
        """
        last_rows = self.store.db.execute(
            """SELECT p.day,p.timestamp_local,p.import_kw,p.export_kw,
                      p.import_quality,p.export_quality
               FROM profile_intervals p
               JOIN (SELECT day,MAX(row_index) AS idx FROM profile_intervals
                     WHERE meter_id=? GROUP BY day) last
                 ON p.day=last.day AND p.row_index=last.idx
               WHERE p.meter_id=?""",
            (meter_id, meter_id),
        ).fetchall()
        incomplete: set[str] = set()
        for day, stamp, imp, exp, iq, eq in last_rows:
            if _last_profile_ok(day, stamp, imp, exp, iq, eq):
                continue
            alternatives = self.store.db.execute(
                """SELECT i.timestamp_local,i.import_kw,i.export_kw,
                          i.import_quality,i.export_quality
                   FROM profile_intervals i
                   JOIN meter_metadata other ON other.meter_id=i.meter_id
                   JOIN meter_metadata current ON current.meter_id=?
                   WHERE i.day=? AND i.meter_id<>?
                     AND other.import_ean=current.import_ean
                   ORDER BY i.row_index DESC""",
                (meter_id, day, meter_id),
            ).fetchall()
            if not any(_last_profile_ok(day, *row) for row in alternatives):
                incomplete.add(day)
        return incomplete

    def plan(
        self,
        meter_id: str,
        start_date: str | date,
        max_days: int,
        configs: Sequence[dict],
    ) -> list[BackfillTask]:
        """Plan earliest gaps, with two-hour and Prague-local daily cooldowns."""
        try:
            start = (
                date.fromisoformat(start_date)
                if isinstance(start_date, str)
                else start_date
            )
        except ValueError as exc:
            raise ValueError("archive_start_date must be YYYY-MM-DD") from exc
        if not isinstance(start, date) or isinstance(start, datetime):
            raise ValueError("archive_start_date must be a calendar date")
        limit = max(1, min(MAX_DAYS_PER_CYCLE, int(max_days)))
        try:
            requested_ids = {int(config["id"]) for config in configs}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Each assembly config requires an integer id") from exc
        if not requested_ids:
            return []
        now, today = self._clock()
        yesterday = today - timedelta(days=1)
        if start > yesterday:
            return []

        recorded: dict[str, dict[int, tuple[bool, datetime | None]]] = {}
        for day, assembly_id, has_data, fetched in self.store.db.execute(
            """SELECT day,assembly_id,has_data,fetched_at_utc
               FROM assembly_responses WHERE meter_id=?""",
            (meter_id,),
        ):
            recorded.setdefault(day, {})[int(assembly_id)] = (
                bool(has_data),
                self._attempt_time(fetched),
            )
        attempts = {
            day: self._attempt_time(when)
            for day, when in self.store.db.execute(
                "SELECT day,attempted_at_utc FROM fetch_attempts WHERE meter_id=?",
                (meter_id,),
            )
        }
        incomplete = self.incomplete_final_days(meter_id)
        tasks: list[BackfillTask] = []
        day = start
        local_tz = ZoneInfo("Europe/Prague")
        while day <= yesterday and len(tasks) < limit:
            key = day.isoformat()
            existing = recorded.get(key, {})
            last_attempt = attempts.get(key)
            if last_attempt and now - last_attempt < MIN_RETRY_INTERVAL:
                day += timedelta(days=1)
                continue
            missing = any(key_id not in existing for key_id in requested_ids)
            recent = day >= today - timedelta(days=4)
            refreshed_today = (
                last_attempt is not None
                and last_attempt.astimezone(local_tz).date() == today
            )
            recent_stale = recent and not refreshed_today
            empty_stale = not recent and any(
                not has_data
                and (fetched_at is None or now - fetched_at >= EMPTY_RETRY_INTERVAL)
                for assembly_id, (has_data, fetched_at) in existing.items()
                if assembly_id in requested_ids
            )
            final_stale = key in incomplete and not refreshed_today
            if missing or recent_stale or empty_stale or final_stale:
                repair_only = (
                    final_stale
                    and not missing
                    and not recent_stale
                    and not empty_stale
                    and PROFILE_ASSEMBLY_ID in requested_ids
                )
                selected = (
                    tuple(c for c in configs if int(c["id"]) == PROFILE_ASSEMBLY_ID)
                    if repair_only
                    else tuple(configs)
                )
                tasks.append(BackfillTask(day, selected, repair_only))
            day += timedelta(days=1)
        return tasks

    def _record_failed_attempt(self, meter_id: str, day: date) -> None:
        now, _ = self._clock()
        with self.store.db:
            self.store.db.execute(
                """INSERT INTO fetch_attempts
                   (meter_id,day,attempted_at_utc,success) VALUES (?,?,?,0)
                   ON CONFLICT(meter_id,day) DO UPDATE SET
                     attempted_at_utc=excluded.attempted_at_utc,success=0""",
                (meter_id, day.isoformat(), now.isoformat(timespec="seconds")),
            )

    async def run(
        self,
        fetcher: Any,
        cookies: list[dict],
        meter_id: str,
        configs: Sequence[dict],
        start_date: str | date,
        max_days: int,
        import_ean: str,
        export_ean: str,
        *,
        rejection_error: type[Exception] | tuple[type[Exception], ...] = (),
    ) -> BackfillResult:
        """Fetch planned days. Stop on explicit portal rejection; never log errors.

        A storage error remains fatal rather than hiding possible DB corruption.
        Caller must pass the actual PND rejection exception class explicitly.
        """
        tasks = self.plan(meter_id, start_date, max_days, configs)
        succeeded = failed = attempted = 0
        paused = False
        for task in tasks:
            attempted += 1
            try:
                response = await fetcher.fetch_all(
                    cookies,
                    meter_id,
                    list(task.assemblies),
                    archive_day=datetime.combine(task.day, time.min),
                    archive_mode=True,
                )
            except Exception as exc:
                self._record_failed_attempt(meter_id, task.day)
                failed += 1
                if rejection_error and isinstance(exc, rejection_error):
                    LOGGER.warning("PND archive paused by portal rejection")
                    paused = True
                    break
                # Exception messages may include private endpoints or tokens.
                LOGGER.warning("PND archive request failed; retry deferred")
                continue
            if not isinstance(response, dict) or not response:
                self._record_failed_attempt(meter_id, task.day)
                failed += 1
                continue
            self.store.save_day(
                meter_id,
                task.day,
                list(task.assemblies),
                response,
                import_ean,
                export_ean,
            )
            succeeded += 1
        return BackfillResult(len(tasks), attempted, succeeded, failed, paused)
