# Consolidated PND repair and optional archive

This is the combined replacement for fork drafts #1–#6 and #11, reviewed against
upstream main f1b2e3f47890eef191cfd2163a6f297968af4cd2 (still current on 2026-11-16).
It includes the previously tested integration preview and the missing MQTT
network-loop fix. It is a review candidate, not a deployed add-on.

## Resulting behavior

- Paho runs its network thread, waits for CONNACK, restores retained discovery
  and per-meter online status on reconnect, and drains outgoing publications
  before disconnecting/stopping the thread. Paho 2.x is required by the existing
  VERSION2 callback API. Unexpected connection loss still uses the original
  first-meter-only LWT; multi-meter atomic availability is not claimed.
- Discovery keeps all sensor unique IDs, domains and state/availability topics.
  The legacy Rv column retains the source's kW unit and unchanged numeric values;
  its incompatible reactive_power class is removed. Physical Rv interpretation
  is unresolved, so no unverified conversion to var/kvar is made. HDO ON/OFF
  remains the existing sensor, with the invalid binary_sensor class removed.
  No retained configuration is deleted and no binary-domain migration occurs.
- Optional SQLite history remains disabled by default. When enabled it shares
  the authenticated client, uses explicit Prague calendar days, includes the
  final midnight endpoint, preserves missing/ambiguous data and applies guarded
  known-legacy view migration. Unknown view definitions are refused.
- Legacy external-broker options, separate archive meter selection and separate
  import/export EANs are preserved. Never infer both EANs from the generic ean.
  Existing metadata conflicts stop the affected archive meter.
- Portal rejection aborts historical requests and activates process-local
  cooldown. A restart resets that cooldown. Archive work is serial and shares a
  global daily-request budget; a large budget can delay normal polling.
- Private response/exception details are suppressed in logs. Missing HDO tokens
  now bootstrap through the authenticated page's DIP token endpoint instead of
  waiting 30 seconds for Angular to populate localStorage. The portal's wrapped
  JSON-string response is unwrapped, validated and passed to the signals request.
  Token values and private responses are never logged. Rejected/HTML/invalid
  token responses fail closed. Production HDO remains unverified until cutover.

## Configuration and downstream compatibility

Public addon/config.yaml uses upstream slug cez-pnd and version 0.4.1. It is not
a drop-in manifest for the existing local cez-pnd-external 0.4.8 installation.
For a controlled local update, preserve that installation's manifest identity,
boot setting and private options; overlay reviewed runtime files and add archive
schema/options without copying private defaults into Git. No parallel publisher.

Archive options: archive_enabled (default false), archive_start_date (YYYY-MM-DD),
archive_days_per_cycle (1–62, default 1), archive_meter_ids (JSON string list),
import_ean/export_ean (separate optional metadata). Normal MQTT meters remain
independent. External broker options remain mqtt_host/port/user/password.

No changes are required to Predbat, SolaX, the price archive or existing SQL
consumers: the database path and pnd_combined_15m contract are preserved. Actual
entity identity and SQL compatibility still require verification at deployment.

## Controlled deployment and rollback

1. Obtain explicit approval before changing the installed add-on or database.
   Refresh source hashes/options privately; version equality is insufficient.
2. Back up the add-on and use SQLite backup API or a consistent stopped snapshot
   including WAL data. Record current per-meter row/quality counts and integrity.
3. Test a copy offline. Preserve local slug and options; start only the replacement,
   archive disabled. Confirm normal PND and stable MQTT beyond three minutes,
   then verify reconnect. Confirm existing sensor identities and HDO isolation.
4. With approval, enable archive at 1–2 days per cycle. Validate metadata, guarded
   view migration, quality and interval-end interpretation against the baseline.
5. Roll back on MQTT identity loss, SQL/quality regression or portal rejections.
   Restore original source/options; restore the DB only if affected, preserving
   any newer successful measurements. Never replace gaps with zero.

## Validation

The single inherited CI workflow now covers Python 3.9–3.13, keeps 80% coverage,
blocks external sockets during synthetic tests, and retains lint/type, secrets,
SAST, dependency audit, Docker/Trivy and SBOM jobs. Redundant fork-only workflow
is removed. Advisory security jobs retain their inherited advisory status; a
successful run does not establish a vulnerability-free production deployment.

## Verified HDO authorization refinement (2026-11-17)

The main DIP dashboard must initialize backend authorization before the detail page. Production diagnosis distinguished HTTP 400 wrapping statusCode=401 from maintenance; visiting the dashboard then yielded a token and HTTP 200 signals. The final client uses a bounded initialization wait with explicit API fallback. Dated schedules select the Prague-local day and next-switch timestamps include the UTC offset. Current operational acceptance results are maintained in PR #2.
