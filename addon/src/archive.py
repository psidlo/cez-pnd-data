"""SQLite core for lossless 15-minute CEZ PND readings.

All API responses are preserved in the private local database; profile rows
retain ordinals so repeated local times at DST transitions do not collide.
This module does not perform network requests, schedule backfills or publish MQTT.
"""
from __future__ import annotations
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3

LOGGER = logging.getLogger(__name__)
DEFAULT_DB_PATH = '/share/cez_pnd/measurements.sqlite3'


def _now_utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _to_decimal(value):
    if value is None or value == '':
        return None
    try:
        return float(str(value).replace(',', '.'))
    except (ValueError, TypeError):
        return None


def _cell(row, col_id):
    if col_id is None or not isinstance(row, dict):
        return {}
    v = row.get(col_id, {})
    return v if isinstance(v, dict) else {}



def _end_of_day_stamp(report_day):
    """The final quarter-hour ends at the following midnight."""
    if isinstance(report_day, str):
        report_day = date.fromisoformat(report_day)
    return {report_day.strftime('%d.%m.%Y') + ' 24:00',
            (report_day + timedelta(days=1)).strftime('%d.%m.%Y 00:00')}


def _profile_measured(import_kw, export_kw, imp_quality, exp_quality):
    """CEZ quality 32 OK; 16 measured during voltage outage (flagged)."""
    return (import_kw is not None and export_kw is not None
            and str(imp_quality) in ('32', '16')
            and str(exp_quality) in ('32', '16'))


def _last_profile_ok(report_day, timestamp, import_kw, export_kw, imp_quality, exp_quality):
    return (timestamp in _end_of_day_stamp(report_day)
            and _profile_measured(import_kw, export_kw, imp_quality, exp_quality))


def _profile_payload_rows(payload, report_day):
    """Filter any spill-over from a request ending at next-day midnight.

    Preserve duplicated local times at autumn DST and the original row JSON.
    A synthetic 23:59 null sentinel is retained for diagnosis unless the
    actual midnight endpoint is present; in that case drop the sentinel.
    """
    columns = payload.get('columns') or []
    timestamp_id = next((str(c.get('id')) for c in columns if c.get('name') == 'Datum'), None)
    import_id = next((str(c.get('id')) for c in columns
                      if str(c.get('name', '')).startswith('+A/') or c.get('name') == 'Profil +A'), None)
    export_id = next((str(c.get('id')) for c in columns
                      if str(c.get('name', '')).startswith('-A/') or c.get('name') == 'Profil -A'), None)
    if not timestamp_id or not import_id or not export_id:
        return [], False, 0
    report_day = date.fromisoformat(report_day) if isinstance(report_day, str) else report_day
    current = report_day.strftime('%d.%m.%Y')
    next_midnight = (report_day + timedelta(days=1)).strftime('%d.%m.%Y 00:00')
    raw_rows = payload.get('values') or []
    rows = [r for r in raw_rows if isinstance(r, dict)
            and ((str(_cell(r, timestamp_id).get('v', '')).startswith(current + ' ')
                  and _cell(r, timestamp_id).get('v') != current + ' 00:00')
                 or _cell(r, timestamp_id).get('v') == next_midnight)]
    contains_real_endpoint = any(_cell(r, timestamp_id).get('v') in _end_of_day_stamp(report_day)
                                 for r in rows)
    if contains_real_endpoint:
        rows = [r for r in rows
                if not (_cell(r, timestamp_id).get('v') == current + ' 23:59'
                        and _to_decimal(_cell(r, import_id).get('v')) is None
                        and _to_decimal(_cell(r, export_id).get('v')) is None)]
    last = rows[-1] if rows else {}
    stamp = _cell(last, timestamp_id).get('v')
    a, b = _cell(last, import_id), _cell(last, export_id)
    ok = _last_profile_ok(report_day, stamp, _to_decimal(a.get('v')), _to_decimal(b.get('v')),
                          a.get('s'), b.get('s'))
    good = sum(1 for r in rows if _profile_measured(
               _to_decimal(_cell(r, import_id).get('v')),
               _to_decimal(_cell(r, export_id).get('v')),
               _cell(r, import_id).get('s'), _cell(r, export_id).get('s')))
    return rows, ok, good

PND_COMBINED_VIEW_SQL = "CREATE VIEW IF NOT EXISTS pnd_combined_15m AS\nWITH p AS (\n SELECT m.import_ean, m.export_ean, i.meter_id, i.day, i.row_index,\n        CASE WHEN substr(i.timestamp_local,12,5)='23:59'\n             THEN substr(i.timestamp_local,1,11)||'24:00'\n             ELSE i.timestamp_local END AS timestamp_local,\n        i.import_kw, i.export_kw, i.import_quality, i.export_quality,\n        ROW_NUMBER() OVER (\n          PARTITION BY i.meter_id, i.day,\n            CASE WHEN substr(i.timestamp_local,12,5)='23:59'\n                 THEN substr(i.timestamp_local,1,11)||'24:00'\n                 ELSE i.timestamp_local END\n          ORDER BY i.row_index\n        ) AS occurrence,\n        CASE WHEN substr(i.timestamp_local,12,5)='23:59' THEN 0\n             WHEN i.import_kw IS NOT NULL AND i.export_kw IS NOT NULL\n             AND i.import_quality IN ('32','16')\n             AND i.export_quality IN ('32','16') THEN 1 ELSE 0 END AS measured,\n        CASE WHEN i.import_quality='8' OR i.export_quality='8' THEN 1 ELSE 0 END AS invalid\n FROM profile_intervals i JOIN meter_metadata m ON i.meter_id=m.meter_id\n WHERE i.timestamp_local IS NOT NULL\n), grouped AS (\n SELECT import_ean, export_ean, day, timestamp_local, occurrence,\n        SUM(measured) AS measured_count,\n        MAX(CASE WHEN measured=1 THEN meter_id END) AS chosen_meter_id,\n        MAX(CASE WHEN measured=1 THEN import_kw END) AS chosen_import_kw,\n        MAX(CASE WHEN measured=1 THEN export_kw END) AS chosen_export_kw,\n        MAX(CASE WHEN measured=1 AND (import_quality='16' OR export_quality='16')\n                 THEN 1 ELSE 0 END) AS has_voltage_warning,\n        MAX(invalid) AS has_invalid\n FROM p\n GROUP BY import_ean, export_ean, day, timestamp_local, occurrence\n)\nSELECT import_ean, export_ean, day, timestamp_local, occurrence,\n       CASE WHEN substr(timestamp_local,12,5)='24:00'\n            THEN date(day,'+1 day')||'T00:00:00'\n            ELSE substr(timestamp_local,7,4)||'-'||substr(timestamp_local,4,2)||'-'||substr(timestamp_local,1,2)||'T'||substr(timestamp_local,12,5)||':00' END AS end_local_iso,\n       CASE WHEN measured_count=1 THEN chosen_meter_id END AS meter_id,\n       CASE WHEN measured_count=1 THEN chosen_import_kw END AS import_kw,\n       CASE WHEN measured_count=1 THEN chosen_export_kw END AS export_kw,\n       CASE WHEN measured_count>1 THEN 'AMBIGUOUS'\n            WHEN measured_count=1 AND has_voltage_warning=1 THEN 'VOLTAGE_OUTAGE'\n            WHEN measured_count=1 THEN 'OK'\n            WHEN has_invalid=1 THEN 'INVALID'\n            ELSE 'UNDEFINED' END AS quality,\n       measured_count\nFROM grouped;"



# SQLite's legacy view incorrectly used the report day for all end times, even
# when the raw timestamp says 00:00 of the following day.
LEGACY_END_LOCAL_EXPR = """ELSE day||'T'||substr(timestamp_local,12,5)||':00'"""
FIXED_END_LOCAL_EXPR = """ELSE substr(timestamp_local,7,4)||'-'||substr(timestamp_local,4,2)||'-'||substr(timestamp_local,1,2)||'T'||substr(timestamp_local,12,5)||':00'"""

class ArchiveStore:
    """SQLite archive storage only; no polling, backfill, HA or MQTT side effects."""

    def __init__(self, path=DEFAULT_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        is_new = not self.path.exists()
        self.db = sqlite3.connect(str(self.path), timeout=30)
        if is_new:
            os.chmod(self.path, 0o600)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=30000')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meter_metadata (
          meter_id TEXT PRIMARY KEY, import_ean TEXT NOT NULL,
          export_ean TEXT NOT NULL, updated_at_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS assembly_responses (
          meter_id TEXT NOT NULL, day TEXT NOT NULL, assembly_id INTEGER NOT NULL,
          assembly_name TEXT NOT NULL, fetched_at_utc TEXT NOT NULL,
          has_data INTEGER NOT NULL, response_rows INTEGER NOT NULL,
          response_json TEXT NOT NULL,
          PRIMARY KEY(meter_id, day, assembly_id)
        );
        CREATE TABLE IF NOT EXISTS profile_intervals (
          meter_id TEXT NOT NULL, day TEXT NOT NULL, row_index INTEGER NOT NULL,
          timestamp_local TEXT, import_kw REAL, export_kw REAL, reactive_kw REAL,
          import_quality TEXT, export_quality TEXT, raw_row_json TEXT NOT NULL,
          PRIMARY KEY(meter_id, day, row_index)
        );
        CREATE INDEX IF NOT EXISTS idx_pnd_interval_lookup
            ON profile_intervals(meter_id, timestamp_local);
        CREATE TABLE IF NOT EXISTS fetch_attempts (
          meter_id TEXT NOT NULL, day TEXT NOT NULL,
          attempted_at_utc TEXT NOT NULL, success INTEGER NOT NULL,
          PRIMARY KEY(meter_id, day)
        );
        """)
        # Read-only normalized projection; creating the view changes schema
        # metadata only. Existing archive rows remain unchanged.
        self._ensure_combined_view()
        self.db.commit()


    def _ensure_combined_view(self):
        """Create the view or upgrade the known legacy expression atomically.

        Never replace an unrelated view with the same name. No measurement
        tables or stored rows are modified by this migration.
        """
        current = self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='view' AND name='pnd_combined_15m'"
        ).fetchone()
        desired = PND_COMBINED_VIEW_SQL.replace('VIEW IF NOT EXISTS', 'VIEW', 1)
        legacy = desired.replace(FIXED_END_LOCAL_EXPR, LEGACY_END_LOCAL_EXPR)

        def equivalent(a, b):
            return ' '.join(a.rstrip(' ;').split()) == ' '.join(b.rstrip(' ;').split())

        if current and equivalent(current[0], desired):
            return
        if current and not equivalent(current[0], legacy):
            raise RuntimeError(
                'Existing pnd_combined_15m view is not a recognized legacy version; '
                'manual review required before modifying schema'
            )
        with self.db:
            if current:
                self.db.execute('DROP VIEW pnd_combined_15m')
            self.db.execute(desired)


    def close(self):
        self.db.close()

    def set_meter_eans(self, meter_id, import_ean, export_ean):
        with self.db:
            self.db.execute("""INSERT INTO meter_metadata
                (meter_id,import_ean,export_ean,updated_at_utc) VALUES (?,?,?,?)
                ON CONFLICT(meter_id) DO UPDATE SET
                import_ean=excluded.import_ean,
                export_ean=excluded.export_ean,
                updated_at_utc=excluded.updated_at_utc""",
                (meter_id, import_ean, export_ean, _now_utc()))

    def save_day(self, meter_id, report_day, configs, result, import_ean, export_ean):
        """Commit each returned assembly and all its rows atomically."""
        day = report_day.isoformat()
        timestamp = _now_utc()
        names_to_ids = {c['name']: c['id'] for c in configs}
        saved_assemblies = 0
        interval_count = 0
        with self.db:
            self.db.execute("""INSERT INTO meter_metadata
                (meter_id,import_ean,export_ean,updated_at_utc) VALUES (?,?,?,?)
                ON CONFLICT(meter_id) DO UPDATE SET
                import_ean=excluded.import_ean, export_ean=excluded.export_ean,
                updated_at_utc=excluded.updated_at_utc""",
                (meter_id, import_ean, export_ean, timestamp))
            for name, payload in result.items():
                if name not in names_to_ids or not isinstance(payload, dict):
                    continue
                assembly_id = names_to_ids[name]
                rows = payload.get('values') or []
                if not isinstance(rows, list):
                    rows = []
                has_data = bool(payload.get('hasData'))
                old_good = self.db.execute("""SELECT has_data FROM assembly_responses
                    WHERE meter_id=? AND day=? AND assembly_id=?""",
                    (meter_id, day, assembly_id)).fetchone()
                # Never replace previously valid data with a later empty response.
                if old_good and old_good[0] and not has_data:
                    continue
                if assembly_id == -1003 and has_data:
                    clean_rows, endpoint_ok, new_good = _profile_payload_rows(payload, day)
                    previously_measured = self.db.execute("""SELECT timestamp_local,
                             import_kw,export_kw,import_quality,export_quality
                        FROM profile_intervals WHERE meter_id=? AND day=?
                        ORDER BY row_index""", (meter_id, day)).fetchall()
                    new_columns = payload.get('columns') or []
                    date_id = next((str(c.get('id')) for c in new_columns if
                                    c.get('name') == 'Datum'), None)
                    imp_id = next((str(c.get('id')) for c in new_columns if
                                   str(c.get('name', '')).startswith('+A/') or
                                   c.get('name') == 'Profil +A'), None)
                    exp_id = next((str(c.get('id')) for c in new_columns if
                                   str(c.get('name', '')).startswith('-A/') or
                                   c.get('name') == 'Profil -A'), None)
                    # Ordinal-per-timestamp handles duplicate 02:xx on DST fallback.
                    old_occ, new_occ, old_keys, new_keys = {}, {}, set(), set()
                    for stamp, imp, exp, iq, eq in previously_measured:
                        old_occ[stamp] = old_occ.get(stamp, 0) + 1
                        if _profile_measured(imp, exp, iq, eq):
                            old_keys.add((stamp, old_occ[stamp]))
                    for raw in clean_rows:
                        stamp = _cell(raw, date_id).get('v')
                        new_occ[stamp] = new_occ.get(stamp, 0) + 1
                        ia, ea = _cell(raw, imp_id), _cell(raw, exp_id)
                        if _profile_measured(_to_decimal(ia.get('v')),
                                             _to_decimal(ea.get('v')),
                                             ia.get('s'), ea.get('s')):
                            new_keys.add((stamp, new_occ[stamp]))
                    degraded = not old_keys.issubset(new_keys)
                    prev_good = len(old_keys)
                    # Keep the last-known good data if a new PND response is incomplete.
                    if old_good and old_good[0] and (not endpoint_ok or new_good < prev_good or degraded):
                        LOGGER.warning('Archive: refreshed profile incomplete; preserving existing measurements')
                        continue
                    if not endpoint_ok:
                        LOGGER.warning('Archive: final 15-minute interval unavailable; retaining gap')
                self.db.execute("""INSERT INTO assembly_responses
                    (meter_id, day, assembly_id, assembly_name, fetched_at_utc,
                     has_data, response_rows, response_json)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(meter_id,day,assembly_id) DO UPDATE SET
                    assembly_name=excluded.assembly_name,
                    fetched_at_utc=excluded.fetched_at_utc,
                    has_data=excluded.has_data,
                    response_rows=excluded.response_rows,
                    response_json=excluded.response_json""",
                    (meter_id, day, assembly_id, name, timestamp, int(has_data),
                     len(rows), json.dumps(payload, ensure_ascii=False, separators=(',', ':'))))
                saved_assemblies += 1
                if assembly_id == -1003 and has_data:
                    columns = payload.get('columns') or []
                    ids = {}
                    for c in columns:
                        n = str(c.get('name', ''))
                        if n == 'Datum': ids['date'] = str(c['id'])
                        elif n.startswith('+A/') or n == 'Profil +A': ids['import'] = str(c['id'])
                        elif n.startswith('-A/') or n == 'Profil -A': ids['export'] = str(c['id'])
                        elif n.startswith('Rv/'): ids['reactive'] = str(c['id'])
                    # PND's "23:59" final sentinel may contain null measurements;
                    # retain it as a raw row rather than fabricating a 15min value.
                    if 'date' not in ids or not ({'import','export'} & set(ids)):
                        LOGGER.warning('Archive: unrecognized profile columns; raw data retained')
                        continue
                    observed_meter_ids = {
                        str(c.get('name', '')).rsplit('/', 1)[1]
                        for c in columns
                        if str(c.get('name', '')).startswith(('+A/', '-A/', 'Rv/'))
                    }
                    if observed_meter_ids and observed_meter_ids != {str(meter_id)}:
                        LOGGER.error('Archive: profile meter mismatch; raw data retained, intervals skipped')
                        continue
                    # Filter next-day spill-over and any redundant 23:59 sentinel;
                    # only replace the previous profile after all checks above.
                    rows = clean_rows
                    self.db.execute('DELETE FROM profile_intervals WHERE meter_id=? AND day=?',
                                    (meter_id, day))
                    for index, row in enumerate(rows):
                        a = _cell(row, ids.get('import'))
                        b = _cell(row, ids.get('export'))
                        r = _cell(row, ids.get('reactive'))
                        d = _cell(row, ids.get('date'))
                        self.db.execute("""INSERT INTO profile_intervals
                            (meter_id,day,row_index,timestamp_local,import_kw,export_kw,reactive_kw,
                             import_quality,export_quality,raw_row_json)
                            VALUES(?,?,?,?,?,?,?,?,?,?)""",
                            (meter_id,day,index,d.get('v'),_to_decimal(a.get('v')),
                             _to_decimal(b.get('v')),_to_decimal(r.get('v')),
                             str(a.get('s')) if a.get('s') is not None else None,
                             str(b.get('s')) if b.get('s') is not None else None,
                             json.dumps(row, ensure_ascii=False, separators=(',', ':'))))
                        interval_count += 1
            # Mark successful only if at least one assembly response was obtained.
            self.db.execute("""INSERT INTO fetch_attempts
                (meter_id,day,attempted_at_utc,success) VALUES (?,?,?,?)
                ON CONFLICT(meter_id,day) DO UPDATE SET
                attempted_at_utc=excluded.attempted_at_utc,
                success=excluded.success""", (meter_id, day, timestamp, int(bool(result))))
        return saved_assemblies, interval_count

    def overview(self, meter_id):
        days = self.db.execute("""SELECT COUNT(DISTINCT day) FROM assembly_responses
            WHERE meter_id=? AND assembly_id=-1003 AND has_data=1""", (meter_id,)).fetchone()[0]
        rows = self.db.execute('SELECT COUNT(*) FROM profile_intervals WHERE meter_id=?',
                               (meter_id,)).fetchone()[0]
        return days, rows
