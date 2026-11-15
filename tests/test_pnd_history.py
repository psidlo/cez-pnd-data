"""Pure synthetic tests: no CEZ account, cookies, meters or network traffic."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from addon.src.pnd_history import pnd_fetch_window


def test_default_live_window_unchanged():
    interval = pnd_fetch_window(now=datetime(2026, 11, 15, 12, 30))
    assert interval.date_from == "15.11.2026 00:00"
    assert interval.date_to == "15.11.2026 23:59"
    assert interval.profile_date_to == interval.date_to


def test_historical_profile_includes_next_midnight():
    interval = pnd_fetch_window(archive_day=date(2026, 11, 14), archive_mode=True)
    assert interval.date_from == "14.11.2026 00:00"
    assert interval.date_to == "14.11.2026 23:59"
    assert interval.profile_date_to == "15.11.2026 00:00"


def test_crosses_year_end():
    interval = pnd_fetch_window(archive_day=date(2026, 12, 31), archive_mode=True)
    assert interval.profile_date_to == "01.01.2027 00:00"


@pytest.mark.parametrize("day", [date(2026, 3, 29), date(2026, 10, 25)])
def test_dsts_do_not_remove_last_interval(day):
    interval = pnd_fetch_window(archive_day=day, archive_mode=True)
    assert interval.date_from == day.strftime("%d.%m.%Y 00:00")
    assert interval.profile_date_to == (day + timedelta(days=1)).strftime(
        "%d.%m.%Y 00:00"
    )


def test_aware_utc_midnight_converted_to_prague_local_day():
    interval = pnd_fetch_window(
        archive_day=datetime(2026, 11, 14, 23, 30, tzinfo=timezone.utc),
        archive_mode=True,
    )
    assert interval.date_from == "15.11.2026 00:00"


def test_aware_prague_date_is_used_without_shifting_calendar():
    interval = pnd_fetch_window(
        archive_day=datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo("Europe/Prague")),
        archive_mode=True,
    )
    assert interval.date_from == "25.10.2026 00:00"


def test_naive_archive_datetime_treated_as_local_date():
    interval = pnd_fetch_window(
        archive_day=datetime(2026, 11, 14), archive_mode=True
    )
    assert interval.date_from == "14.11.2026 00:00"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"archive_mode": True},
        {"archive_day": date(2026, 11, 14)},
        {"archive_mode": True, "archive_day": "2026-11-14"},
        {"now": "2026-11-15"},
    ],
)
def test_invalid_arguments_fail_before_network(kwargs):
    with pytest.raises(ValueError):
        pnd_fetch_window(**kwargs)
