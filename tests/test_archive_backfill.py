"""Synthetic-only backfill tests; no personal meters, credentials or requests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from addon.src.archive import ArchiveStore
from addon.src.archive_backfill import ArchiveBackfill, MAX_DAYS_PER_CYCLE

NOW = datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc)
CONFIG = [
    {"id": -1003, "name": "profile"},
    {"id": -2000, "name": "summary"},
]


def make_store(tmp_path):
    return ArchiveStore(tmp_path / "synthetic.sqlite3")


def mark_assembly(store, day, assembly_id, *, has_data=True, fetched_at=None, meter_id="123"):
    store.db.execute(
        """INSERT OR REPLACE INTO assembly_responses
           (meter_id,day,assembly_id,assembly_name,fetched_at_utc,has_data,
            response_rows,response_json) VALUES(?,?,?,?,?,?,?,?)""",
        (meter_id, day, assembly_id, "synthetic", (fetched_at or NOW).isoformat(), int(has_data), 0, "{}"),
    )
    store.db.commit()


def mark_attempt(store, day, when, meter_id="123"):
    store.db.execute(
        """INSERT OR REPLACE INTO fetch_attempts
           (meter_id,day,attempted_at_utc,success) VALUES(?,?,?,?)""",
        (meter_id, day, when.isoformat(), 0),
    )
    store.db.commit()


def mark_last(store, day, stamp, meter_id="123", ean="SYNTHETIC_SITE", quality="32"):
    store.set_meter_eans(meter_id, ean, "SYNTHETIC_EXPORT")
    store.db.execute(
        """INSERT OR REPLACE INTO profile_intervals
           (meter_id,day,row_index,timestamp_local,import_kw,export_kw,
            reactive_kw,import_quality,export_quality,raw_row_json)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (meter_id, day, 0, stamp, 0.5, 0.1, None, quality, quality, "{}"),
    )
    store.db.commit()


def scheduler(store, at=NOW):
    return ArchiveBackfill(store, now=lambda: at)


def test_oldest_missing_days_first_and_no_today(tmp_path):
    store = make_store(tmp_path)
    try:
        tasks = scheduler(store).plan("123", "2026-11-12", 2, CONFIG)
        assert [str(t.day) for t in tasks] == ["2026-11-12", "2026-11-13"]
        assert scheduler(store).plan("123", "2026-11-15", 2, CONFIG) == []
    finally:
        store.close()


def test_retry_cooldown_excludes_recently_failed_day(tmp_path):
    store = make_store(tmp_path)
    try:
        mark_attempt(store, "2026-11-11", NOW - timedelta(minutes=10))
        planned = scheduler(store).plan("123", "2026-11-11", 2, CONFIG)
        assert [str(t.day) for t in planned] == ["2026-11-12", "2026-11-13"]
    finally:
        store.close()


def test_recent_day_refresh_once_per_prague_date(tmp_path):
    at = datetime(2026, 11, 15, 0, 30, tzinfo=timezone.utc)
    store = make_store(tmp_path)
    try:
        for c in CONFIG:
            mark_assembly(store, "2026-11-14", c["id"])
        # UTC day 2026-11-14 but Prague local day already 2026-11-15.
        mark_attempt(store, "2026-11-14", datetime(2026, 11, 14, 23, 20, tzinfo=timezone.utc))
        assert scheduler(store, at).plan("123", "2026-11-14", 2, CONFIG) == []
        mark_attempt(store, "2026-11-14", datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc))
        assert [str(x.day) for x in scheduler(store, at).plan("123", "2026-11-14", 2, CONFIG)] == ["2026-11-14"]
    finally:
        store.close()


def test_old_empty_assembly_retried_after_seven_days(tmp_path):
    store = make_store(tmp_path)
    try:
        day = "2026-10-25"
        for c in CONFIG:
            mark_assembly(store, day, c["id"], has_data=c["id"] != -2000, fetched_at=NOW - timedelta(days=8))
        mark_attempt(store, day, NOW - timedelta(days=8))
        planned = scheduler(store).plan("123", day, 1, CONFIG)
        assert [str(t.day) for t in planned] == [day]
        assert not planned[0].repair_only
    finally:
        store.close()


def test_incomplete_final_retries_profile_only_and_respects_other_meter(tmp_path):
    store = make_store(tmp_path)
    try:
        day = "2026-10-24"
        for c in CONFIG:
            mark_assembly(store, day, c["id"])
        mark_attempt(store, day, NOW - timedelta(days=1))
        mark_last(store, day, "24.10.2026 23:45")
        tasks = scheduler(store).plan("123", day, 1, CONFIG)
        assert len(tasks) == 1
        assert tasks[0].repair_only
        assert [c["id"] for c in tasks[0].assemblies] == [-1003]
        # Replacement meter belongs to the same supply and has valid endpoint.
        mark_last(store, day, "24.10.2026 24:00", meter_id="456")
        assert day not in {str(t.day) for t in scheduler(store).plan("123", day, 1, CONFIG)}
        # A valid endpoint on an unrelated supply must not hide the gap.
        store.set_meter_eans("456", "OTHER_SYNTHETIC_SUPPLY", "SYNTHETIC_EXPORT")
        assert len(scheduler(store).plan("123", day, 1, CONFIG)) == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_successful_fetch_delegates_and_records_without_fabricating_data(tmp_path):
    store = make_store(tmp_path)
    try:
        fetcher = AsyncMock()
        fetcher.fetch_all.return_value = {"summary": {"hasData": False, "values": []}}
        status = await scheduler(store).run(
            fetcher, [], "123", CONFIG, "2026-11-14", 1,
            "SYNTHETIC_SITE", "SYNTHETIC_EXPORT",
        )
        assert (status.planned, status.attempted, status.succeeded, status.failed) == (1, 1, 1, 0)
        assert fetcher.fetch_all.await_count == 1
        args = fetcher.fetch_all.await_args
        assert args.kwargs["archive_mode"] is True
        assert args.kwargs["archive_day"] == datetime(2026, 11, 14)
        assert store.db.execute("SELECT count(*) FROM profile_intervals").fetchone() == (0,)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_rejection_stops_batch_and_persists_cooldown_without_leaking(tmp_path, caplog):
    class PndRejected(Exception):
        pass

    store = make_store(tmp_path)
    try:
        fetcher = AsyncMock()
        fetcher.fetch_all.side_effect = PndRejected("PRIVATE_TOKEN=do_not_log")
        status = await scheduler(store).run(
            fetcher, [], "123", CONFIG, "2026-11-12", 3,
            "SYNTHETIC_SITE", "SYNTHETIC_EXPORT", rejection_error=PndRejected,
        )
        assert status.planned == 3 and status.attempted == 1
        assert status.failed == 1 and status.paused_by_rejection
        assert fetcher.fetch_all.await_count == 1
        assert store.db.execute("SELECT success FROM fetch_attempts WHERE day='2026-11-12'").fetchone() == (0,)
        assert "do_not_log" not in caplog.text
        assert scheduler(store).plan("123", "2026-11-12", 1, CONFIG)[0].day == date(2026, 11, 13)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_other_network_failure_continues_with_cooldown(tmp_path, caplog):
    store = make_store(tmp_path)
    try:
        fetcher = AsyncMock()
        fetcher.fetch_all.side_effect = [RuntimeError("secret diagnostic"), {"summary": {"hasData": False, "values": []}}]
        result = await scheduler(store).run(
            fetcher, [], "123", CONFIG, "2026-11-12", 2,
            "SYNTHETIC_SITE", "SYNTHETIC_EXPORT",
        )
        assert (result.succeeded, result.failed, result.paused_by_rejection) == (1, 1, False)
        assert "secret diagnostic" not in caplog.text
        assert store.db.execute("SELECT count(*) FROM fetch_attempts").fetchone()[0] == 2
    finally:
        store.close()


def test_clamps_batch_limit_and_rejects_bad_dates(tmp_path):
    store = make_store(tmp_path)
    try:
        s = scheduler(store)
        assert len(s.plan("123", "2026-01-01", 1000, CONFIG)) == MAX_DAYS_PER_CYCLE
        with pytest.raises(ValueError):
            s.plan("123", "2026-1-1", 1, CONFIG)
        with pytest.raises(ValueError):
            s.plan("123", date(2026, 11, 15), 1, [{"not": "a config"}])
    finally:
        store.close()


def test_recent_incomplete_day_gets_full_daily_refresh(tmp_path):
    store = make_store(tmp_path)
    try:
        day = "2026-11-13"
        for config in CONFIG:
            mark_assembly(store, day, config["id"])
        mark_attempt(store, day, NOW - timedelta(days=1))
        mark_last(store, day, "13.11.2026 23:45")
        tasks = scheduler(store).plan("123", day, 1, CONFIG)
        assert len(tasks) == 1
        assert not tasks[0].repair_only
        assert [c["id"] for c in tasks[0].assemblies] == [-1003, -2000]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_empty_response_is_not_counted_as_success(tmp_path):
    store = make_store(tmp_path)
    try:
        fetcher = AsyncMock()
        fetcher.fetch_all.return_value = {}
        report = await scheduler(store).run(
            fetcher, [], "123", CONFIG, "2026-11-14", 1,
            "SYNTHETIC_SITE", "SYNTHETIC_EXPORT",
        )
        assert (report.planned, report.attempted, report.succeeded, report.failed) == (1, 1, 0, 1)
        assert store.db.execute("SELECT success FROM fetch_attempts").fetchone() == (0,)
    finally:
        store.close()


def test_old_empty_assembly_not_retried_before_week(tmp_path):
    store = make_store(tmp_path)
    try:
        day = "2026-10-25"
        for c in CONFIG:
            mark_assembly(
                store, day, c["id"], has_data=c["id"] != -2000,
                fetched_at=NOW - timedelta(days=2),
            )
        mark_attempt(store, day, NOW - timedelta(days=2))
        assert day not in {str(t.day) for t in scheduler(store).plan("123", day, 1, CONFIG)}
    finally:
        store.close()


def test_naive_clock_is_not_accepted(tmp_path):
    store = make_store(tmp_path)
    try:
        with pytest.raises(ValueError, match="timezone aware"):
            scheduler(store, datetime(2026, 11, 15)).plan("123", "2026-11-14", 1, CONFIG)
    finally:
        store.close()
