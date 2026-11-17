# PND cutover checks and accepted limits

Dated production verification evidence is maintained in [PR #2](https://github.com/psidlo/cez-pnd-data/pull/2). These checks define completion; the PR records which have actually passed.

| Check | Acceptance criterion |
| --- | --- |
| Local deployment | Preserve local cez-pnd-external identity, broker options and actual boot mode. Capture source/options and a consistent SQLite backup; verify hashes and migration on a copy. |
| HDO authorization | Initialize the main DIP dashboard before the detail page; obtain a valid token and real HTTP 200 signals response. HTTP 400 wrapping statusCode=401 is authorization failure, not maintenance. Never log tokens or response bodies. |
| HDO date/time | Select today's Prague entry, reject stale dated schedules, publish a valid UTC offset and confirm HA accepts next_switch. |
| MQTT stability | Observe import/export and retained availability beyond three keepalive periods; confirm availability after an app reconnect. Automatic transport recovery also has lifecycle tests. Do not restart an unrelated shared broker. |
| Archive | Verify integrity, metadata, view contract, source rows and quality; enable an initial global budget of 1 day/cycle, observe a real cycle, preserve current/retired meters and keep missing values missing. |
| Shutdown | SIGTERM cancels polling and executes MQTT/browser/archive cleanup; tests cover normal stop, worker failure and cancellation. |

## Accepted limits

| Limitation | Consequence |
| --- | --- |
| Process-local rejection cooldown | Restart clears backoff; avoid restart loops during CEZ rejection. Persistence is future hardening. |
| First-meter MQTT LWT | Fits the current single published meter; archive-only meters create no MQTT entities. Multiple published meters lack atomic offline status. |
| Serial backfill | Large budgets can delay normal polling; keep a small global budget. |
| Legacy Rv meaning unverified | Preserve source kW/values and omit the incompatible class; do not invent conversion to var/kvar. |
| Last-known MQTT values | Carry-forward across null rows preserves the local display contract. This does not fill the archive or establish freshness for every metric; billing analysis uses the archive. |
| Missing daily registers | Keep unknown/missing, never synthesize zero. |
| Advisory security jobs | Green CI does not establish vulnerability-free dependencies/images; broad inherited style modernization is outside this repair. |

See [migration and rollback](pnd-consolidated-migration.md). Restore source/options narrowly and preserve newer successful measurements.
