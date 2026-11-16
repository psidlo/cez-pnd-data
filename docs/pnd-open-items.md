# Remaining PND work — 2026-11-16

The implementation is consolidated in fork PR #2. Its scope includes MQTT
network-loop/reconnect repair, discovery compatibility, optional historical
archive, rejection backoff and redacted diagnostics. No production update or
upstream submission has been performed.

## Required before declaring production repair complete

| Item | Current evidence | Next action |
| --- | --- | --- |
| HDO token acquisition in the running installation | Code now bootstraps the token in the authenticated browser page. Current public DIP AuthService uses `/rest-auth-api?path=/token/get`; the HTTP interceptor unwraps `response.data`. Synthetic tests execute the actual JavaScript with wrapped/direct/malformed token responses. The installed 0.4.8 still runs the old wait. | Approve a controlled local update and confirm a real nonempty HDO signals response and successful parsing. A separate HTTP-only diagnostic did not establish an authenticated HDO session and is not counted as success. Do not infer invalid saved credentials from it. |
| Safe local deployment | Public manifest remains upstream cez-pnd 0.4.1, distinct from installed cez-pnd-external 0.4.8. | Refresh private source/options, retain local identity and boot setting, take a consistent SQLite backup, apply the reviewed overlay and verify rollback. Explicit deployment approval required. |
| MQTT stability | Synthetic lifecycle/reconnect/discovery tests pass; no installed-code replacement yet. | After deployment observe availability beyond three keepalive periods and across reconnect; verify current entity identities and values. |
| Archive migration and live compatibility | Guarded legacy-view migration and synthetic archive tests exist. | During approved cutover verify copied/real schema, integrity, metadata, per-meter counts and gaps. Enable archive deliberately with 1–2 days/cycle; do not silently restore budget 50. |

## Known limitations, not new blocking projects

| Limitation | Practical consequence |
| --- | --- |
| Rejection cooldown is process-local | An app restart clears the backoff. Avoid restart loops while CEZ is rejecting requests. Persisting cooldown is future hardening. |
| MQTT LWT covers the first published meter | Current single-MQTT-meter configuration fits this constraint; multiple simultaneously published meters do not have atomic offline status. Archive-only meters do not create MQTT entities. |
| Backfill runs serially with normal polling | A large history budget may delay the next live poll. Keep a small global budget during initial operation. |
| Legacy Rv meaning is not verified | Preserve source kW and numeric values, omit incompatible reactive_power class. Do not invent a var/kvar conversion. |
| Daily registers can legitimately have no source data | Keep unknown/missing; never synthesize zero. Reassess only with real source responses. |
| Security jobs retain upstream advisory policy | Successful CI does not promise all dependencies/images are vulnerability-free. Broader inherited style modernization is also outside this repair. |

Source details, prior test runs and migration steps remain in Git history and
[pnd-consolidated-migration.md](pnd-consolidated-migration.md). No additional
supporting PR is needed to track these items.
