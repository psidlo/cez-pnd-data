"""Synthetic-only regression tests: no real meter, EAN, or response data."""

from __future__ import annotations

from datetime import date

from addon.src.archive import ArchiveStore

COLUMNS = [
    {"id": "t", "name": "Datum"},
    {"id": "i", "name": "+A/123"},
    {"id": "e", "name": "-A/123"},
]
CONFIG = [{"name": "profile_all", "id": -1003}]


def reading(
    timestamp: str,
    import_kw: str | None = "0,4",
    export_kw: str | None = "0,0",
    quality: str = "32",
) -> dict:
    return {
        "t": {"v": timestamp},
        "i": {"v": import_kw, "s": quality},
        "e": {"v": export_kw, "s": quality},
    }


def store_day(
    store: ArchiveStore, day: str, rows: list[dict], meter_id: str = "123"
) -> tuple[int, int]:
    return store.save_day(
        meter_id,
        date.fromisoformat(day),
        CONFIG,
        {"profile_all": {"hasData": True, "columns": COLUMNS, "values": rows}},
        "TEST_IMPORT_EAN",
        "TEST_EXPORT_EAN",
    )


def test_interval_ending_at_next_day_midnight_uses_actual_timestamp_date(tmp_path):
    store = ArchiveStore(tmp_path / "archive.sqlite3")
    try:
        assert store_day(
            store,
            "2026-11-14",
            [reading("14.11.2026 23:45"), reading("15.11.2026 00:00")],
        ) == (1, 2)
        data = store.db.execute(
            "SELECT timestamp_local, end_local_iso FROM pnd_combined_15m ORDER BY end_local_iso"
        ).fetchall()
        assert data == [
            ("14.11.2026 23:45", "2026-11-14T23:45:00"),
            ("15.11.2026 00:00", "2026-11-15T00:00:00"),
        ]
    finally:
        store.close()


def test_24_hour_sentinel_uses_following_midnight(tmp_path):
    store = ArchiveStore(tmp_path / "archive.sqlite3")
    try:
        store_day(store, "2026-11-14", [reading("14.11.2026 24:00")])
        assert (
            store.db.execute("SELECT end_local_iso FROM pnd_combined_15m").fetchone()[0]
            == "2026-11-15T00:00:00"
        )
    finally:
        store.close()


def test_repeated_day_is_idempotent_and_degraded_refresh_is_ignored(tmp_path):
    store = ArchiveStore(tmp_path / "archive.sqlite3")
    try:
        rows = [reading("14.11.2026 23:45"), reading("15.11.2026 00:00")]
        assert store_day(store, "2026-11-14", rows) == (1, 2)
        assert store_day(store, "2026-11-14", rows) == (1, 2)
        assert store.db.execute(
            "SELECT count(*) FROM profile_intervals"
        ).fetchone() == (2,)
        assert store_day(store, "2026-11-14", rows[:-1]) == (0, 0)
        assert store.db.execute(
            "SELECT count(*) FROM profile_intervals"
        ).fetchone() == (2,)
    finally:
        store.close()


def test_missing_values_are_not_assigned_zero(tmp_path):
    store = ArchiveStore(tmp_path / "archive.sqlite3")
    try:
        store_day(store, "2026-11-14", [reading("15.11.2026 00:00", None, None)])
        assert store.db.execute(
            "SELECT import_kw, export_kw, quality FROM pnd_combined_15m"
        ).fetchone() == (None, None, "UNDEFINED")
    finally:
        store.close()


def test_duplicate_autumn_dst_timestamps_keep_both_occurrences(tmp_path):
    store = ArchiveStore(tmp_path / "archive.sqlite3")
    try:
        rows = [
            reading("25.10.2026 02:15", "0,2"),
            reading("25.10.2026 02:15", "0,3"),
            reading("26.10.2026 00:00"),
        ]
        store_day(store, "2026-10-25", rows)
        observed = store.db.execute(
            "SELECT occurrence, import_kw, quality FROM pnd_combined_15m WHERE timestamp_local='25.10.2026 02:15' ORDER BY occurrence"
        ).fetchall()
        assert observed == [(1, 0.2, "OK"), (2, 0.3, "OK")]
    finally:
        store.close()


def test_upgrade_known_legacy_view_without_losing_measurements(tmp_path):
    import sqlite3

    from addon.src.archive import (
        FIXED_END_LOCAL_EXPR,
        LEGACY_END_LOCAL_EXPR,
        PND_COMBINED_VIEW_SQL,
    )

    db_path = tmp_path / "existing.sqlite3"
    store = ArchiveStore(db_path)
    try:
        store_day(store, "2026-11-14", [reading("15.11.2026 00:00")])
    finally:
        store.close()

    legacy_sql = PND_COMBINED_VIEW_SQL.replace(
        FIXED_END_LOCAL_EXPR, LEGACY_END_LOCAL_EXPR
    )
    with sqlite3.connect(db_path) as db:
        db.execute("DROP VIEW pnd_combined_15m")
        db.execute(legacy_sql)
        assert db.execute("SELECT end_local_iso FROM pnd_combined_15m").fetchone() == (
            "2026-11-14T00:00:00",
        )

    restored = ArchiveStore(db_path)
    try:
        assert restored.db.execute(
            "SELECT end_local_iso FROM pnd_combined_15m"
        ).fetchone() == ("2026-11-15T00:00:00",)
        assert restored.db.execute(
            "SELECT count(*) FROM profile_intervals"
        ).fetchone() == (1,)
        assert restored.db.execute(
            "SELECT count(*) FROM assembly_responses"
        ).fetchone() == (1,)
    finally:
        restored.close()

    # Opening the already-upgraded database a second time is a no-op.
    reopened = ArchiveStore(db_path)
    reopened.close()


def test_unknown_existing_view_is_not_overwritten(tmp_path):
    import sqlite3

    db_path = tmp_path / "custom.sqlite3"
    store = ArchiveStore(db_path)
    store.close()
    with sqlite3.connect(db_path) as db:
        db.execute("DROP VIEW pnd_combined_15m")
        db.execute("CREATE VIEW pnd_combined_15m AS SELECT 42 AS custom_value")

    import pytest

    with pytest.raises(RuntimeError, match="manual review required"):
        ArchiveStore(db_path)
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT custom_value FROM pnd_combined_15m").fetchone() == (
            42,
        )


def test_profile_mismatch_logging_never_exposes_requested_or_observed_meter(
    tmp_path, caplog
):
    import logging

    requested = "SYNTHETIC_REQUESTED_PRIVATE"
    observed = "SYNTHETIC_OBSERVED_PRIVATE"
    columns = [
        {"id": "t", "name": "Datum"},
        {"id": "i", "name": "+A/" + observed},
        {"id": "e", "name": "-A/" + observed},
    ]
    payload = {
        "profile_all": {
            "hasData": True,
            "columns": columns,
            "values": [reading("15.11.2026 00:00")],
        }
    }
    store = ArchiveStore(tmp_path / "private.sqlite3")
    try:
        with caplog.at_level(logging.WARNING):
            store.save_day(
                requested,
                date(2026, 11, 14),
                CONFIG,
                payload,
                "SYNTHETIC_IMPORT_EAN",
                "SYNTHETIC_EXPORT_EAN",
            )
        assert "meter mismatch" in caplog.text
        assert requested not in caplog.text
        assert observed not in caplog.text
        assert "SYNTHETIC_IMPORT_EAN" not in caplog.text
    finally:
        store.close()


def test_unrecognized_columns_logging_never_exposes_meter(tmp_path, caplog):
    import logging

    private_meter = "SYNTHETIC_METER_PRIVATE"
    payload = {
        "profile_all": {
            "hasData": True,
            "columns": [{"id": "t", "name": "Datum"}],
            "values": [reading("15.11.2026 00:00")],
        }
    }
    store = ArchiveStore(tmp_path / "unknown.sqlite3")
    try:
        with caplog.at_level(logging.WARNING):
            store.save_day(
                private_meter,
                date(2026, 11, 14),
                CONFIG,
                payload,
                "SYNTHETIC_IMPORT_EAN",
                "SYNTHETIC_EXPORT_EAN",
            )
        assert "unrecognized profile columns" in caplog.text
        assert private_meter not in caplog.text
    finally:
        store.close()
