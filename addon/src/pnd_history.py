"""Date-window contract for optional ČEZ PND historic fetching.

The ordinary live fetch window stays unchanged; a historical query must opt
in explicitly, and historical profile data includes next-day midnight.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo


class PndFetchWindow(NamedTuple):
    date_from: str
    date_to: str
    profile_date_to: str


def pnd_fetch_window(
    *,
    archive_day: date | datetime | None = None,
    archive_mode: bool = False,
    now: datetime | None = None,
) -> PndFetchWindow:
    """Return the requested Czech-local day window without consulting PND.

    ``archive_day`` must be accompanied by ``archive_mode=True``. Naive
    datetime values represent a Prague-local calendar day; aware values are
    converted to Prague first. The live default deliberately retains the
    original add-on's local-calendar-day selection.
    """
    if archive_mode:
        if archive_day is None:
            raise ValueError("archive_day is required in archive_mode")
        if isinstance(archive_day, datetime):
            day = (
                archive_day.astimezone(ZoneInfo("Europe/Prague")).date()
                if archive_day.tzinfo is not None
                and archive_day.utcoffset() is not None
                else archive_day.date()
            )
        elif isinstance(archive_day, date):
            day = archive_day
        else:
            raise ValueError("archive_day must be a date or datetime")
    else:
        if archive_day is not None:
            raise ValueError("archive_day requires archive_mode=True")
        clock = now if now is not None else datetime.now()
        if not isinstance(clock, datetime):
            raise ValueError("now must be a datetime")
        day = clock.date()

    start = day.strftime("%d.%m.%Y 00:00")
    last_minute = day.strftime("%d.%m.%Y 23:59")
    profile_end = (
        (day + timedelta(days=1)).strftime("%d.%m.%Y 00:00")
        if archive_mode
        else last_minute
    )
    return PndFetchWindow(start, last_minute, profile_end)
