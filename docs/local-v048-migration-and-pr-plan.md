# CEZ PND v0.4.8: source audit and upstreamable PR plan

_Status: audit in progress (2026-11-15). This is a planning branch, not a deployment branch. Source code from the running add-on has **not** been imported._

## Repositories and verified baselines

| Source | Ref | Notes |
|---|---|---|
| Original upstream | [Muriel2Horak/cez-pnd-data](https://github.com/Muriel2Horak/cez-pnd-data) `main` | Add-on 0.4.1; source of PR bases |
| Existing development | [honza-kasik/cez-pnd-data](https://github.com/honza-kasik/cez-pnd-data) `main` | Add-on 0.5.0; 23 commits ahead of upstream; contains substantial MQTT, PND, HDO and tests |
| Existing upstream proposal | [PR #18](https://github.com/Muriel2Horak/cez-pnd-data/pull/18) | Open draft, head `honza-kasik:upstream/functional-fixes`; 44 changed files; 4 commits ahead of upstream |
| Our fork | [psidlo/cez-pnd-data](https://github.com/psidlo/cez-pnd-data) `main` | Clean upstream fork, not a v0.4.8 copy |
| Operating add-on | HA Supervisor `local_cez-pnd-external` | v0.4.8, maintained locally; no change as part of this plan |

Honza's `fix/mqtt-recovery-and-upgrade-compatibility` is an **older ancestor of his main** (0 ahead / 6 behind main). His HDO schedule PR #6 and MQTT PR #5 are merged into his own fork; neither implies that upstream accepted the features. Honza's `main` is **23 commits** ahead of original upstream, while PR #18 contains a **4-commit** selection.

The upstream and Honza fork have the same blob SHA for `addon/src/dip_client.py` (`44abb4c653f0514cc7e2c374538c272ca227d09b`). Both currently wait 30 s on `localStorage.getItem('dip-request-token')`; PR #18 does not fix token acquisition.

## Audit of the actual local v0.4.8 archive (2026-11-15)

A source backup named `cez_pnd_external_261115.tar.gz` was received and inspected **outside GitHub**, not pushed. The archive contains 16 active files under `addons/cez_pnd_external` and multiple historical local backups; the latter are excluded from any publication.

Computed Git blob hashes of active files were compared against both repository trees:

| Active local file(s) | Compared with original upstream | Compared with Honza main |
|---|---|---|
| `src/dip_client.py` | Identical | Identical |
| `src/auth.py`, `src/hdo_parser.py`, `src/session_manager.py` | Identical | Different (Honza has other fixes) |
| `src/archive.py` | Local-only | Local-only |
| `src/main.py`, `src/orchestrator.py`, `src/mqtt_publisher.py`, `src/parser.py` | Different | Different |
| `config.yaml`, `run.sh` | Different | Different |
| `Dockerfile`, `requirements.txt`, `src/cookie_utils.py`, `src/__init__.py` | Identical | Most unchanged |

Security: the active local add-on `config.yaml` contains a concrete local MQTT broker address and real electricity-supply identifiers; `run.sh` contains hard-coded supply-point identifiers and meter-specific archive defaults. They must **never** be copied verbatim into a public branch. Inspect any old backup contents separately before considering publication. No credentials, database content, private identifiers or unreviewed whole-tree snapshot have been committed.

A synthetic test of `src/archive.py` found an additional **real bug**: `pnd_combined_15m.end_local_iso` assumes the date part of a non-`24:00` timestamp equals `day`. The last interval of 2026-11-14 with real endpoint `15.11.2026 00:00` becomes `2026-11-14T00:00:00` rather than `2026-11-15T00:00:00`. Proposed archive SQL uses the source timestamp's DD.MM.YYYY date unless the special `24:00` representation applies. Five synthetic tests passed offline for this correction, including repeated-day idempotence, incomplete refresh preservation, missing-value handling and DST duplicated wall-clock times. These are **not** yet upstream CI results. **Production verification:** read-only SQL against `/share/cez_pnd/measurements.sqlite3` found 5,188 existing view rows, 54 end-of-day rows normalized to `24:00`, and 0 records with a next-day literal `00:00` timestamp. Thus the bug is confirmed for the tested input format but no existing affected historical row was found. **Upgrade caveat:** the current `CREATE VIEW IF NOT EXISTS` statement will not replace an existing production view when the source SQL is modified; a separately tested view migration is needed.

Archive extraction found no deployable source-level fix for the DIP token: local `dip_client.py` is byte-for-byte the upstream one. The token root cause still requires controlled browser diagnostics.

Candidate split: `feat/pnd-archive-core` (standalone SQLite schema/projection, quality/DST regression tests), then separate `feat/pnd-archive-backfill` (fetch scheduling and backfill), then separate `feat/pnd-archive-addon-wiring` (optional config and runtime integration). Because there is no independently usable core import in the upstream currently, do not file an unconnected production PR as finished until dependencies and compatibility are resolved.

## Implemented in our fork (2026-11-15)

- [Draft PR #1 — Playwright HDO timeout classification](https://github.com/psidlo/cez-pnd-data/pull/1): a small two-file fix adding explicit Playwright timeout handling and a focused regression test. **Not** a fix for token availability.
- [Draft PR #2 — independent SQLite archive core](https://github.com/psidlo/cez-pnd-data/pull/2): exactly two public source/test files, fully reviewed against the attached local backup, synthetic fixtures only. Storage and schema projection, correction of next-day literal midnight, guarded migration of the known legacy SQLite view without touching stored measurements. Deliberately **excludes** backfill scheduling, fetching and HA runtime wiring.
- Draft PR #2: 7 isolated synthetic tests passed with Python 3.13; compilation and restricted-content checks passed. **Full original CI matrix not yet verified; GitHub workflow runs have not been reported.** The code was not installed or run inside HA.
- Source file hashes were checked after GitHub upload against the locally reviewed byte-for-byte files; public branch contains no real household identifiers, network addresses, credentials or captured measurement data.
- Follow-up candidates: `feat/pnd-archive-backfill` then `feat/pnd-archive-addon-wiring`; the latter must preserve default upstream behavior and compatibility. If upstream prefers one functional PR, prepare a combined review without losing separable commits.

## Backfill implementation prepared (2026-11-15)

- [Draft PR #3 — rate-limited PND backfill](https://github.com/psidlo/cez-pnd-data/pull/3) **stacks onto PR #2** (`feat/pnd-archive-core`), changing exactly `addon/src/archive_backfill.py` and `tests/test_archive_backfill.py`. It adds no separate copy of archive-core files to its diff.
- **20/20 synthetic tests passed** locally: 13 backfill + 7 archive store tests. Source and test Git blob hashes match the tested files; all identifiers in fixtures are synthetic, and a scan against identifiers found in the user's backup found no private identifier matches. GitHub Actions/CI not yet observed.
- Backfill plans bounded historical refreshes in Europe/Prague, obeys two-hour rejection cooldown, weekly rechecks for old empty assemblies, recent-day daily refresh, and same-EAN replacement meter handling. Network access is injected rather than hard-coded. Rejections stop the batch and exception strings are never logged.
- The original 0.4.8 implementation is used as behavioral reference but **no original private configuration, database, credential/session state, or backup files** were uploaded. The running local add-on was not modified.
- Next: run broader Python compatibility checks, review archive-core/backfill interfaces before optional HA wiring, and independently diagnose the unresolved HDO token behavior. No production deployment or upstream submission authorized.

## Track A — HDO token regression (priority)

Observed in the running v0.4.8 add-on after successful DIP login on 2026-11-15:

- Browser opens `https://dip.cezdistribuce.cz/irj/portal/prehled-om`.
- `page.wait_for_function("() => localStorage.getItem('dip-request-token') !== null")` raises a Playwright timeout after 30 seconds.
- The outer handler reports `HDO_FETCH_ERROR`; HDO sensors remain `unknown` while the PND cycle and archive finish successfully.
- The inner `except (TimeoutError, asyncio.TimeoutError)` does not explicitly catch `playwright.async_api.TimeoutError`. This weakens diagnostics, but **is not proven to cause the missing token**.

### Diagnostic plan

1. In a read-only browser session, determine sanitized final URL origin/path, navigation status, whether required application resources loaded, whether expected storage keys are present **by boolean only**, and whether the application emits a suitable request-token API/response event. No token/cookie/session values, EAN, credentials, page dumps or raw network bodies in public logs.
2. Determine whether the correct authenticated page/context is in use. Check redirects, error/maintenance pages and the expected request path.
3. Correct timeout classification independently with a focused regression test. Keep that PR separate if useful.
4. Implement the smallest tested acquisition fix; reauthenticate safely if the existing context is stale. Avoid assumptions about browser storage or production API changes.
5. Keep PND/SQLite operations independent from HDO failures, preserve MQTT topic/unique-ID contracts.
6. Before any deployment, run tests and review a rollback plan. Home Assistant add-on, Predbat and SolaX remain untouched until explicit approval.

## Track B — source migration / PR extraction

### Safety gates

1. Treat `/addons/cez_pnd_external` as **untrusted to publish** until each included file is reviewed; no direct whole-directory `git add`, `git push` or copy to a public branch.
2. Export only code, test fixtures, sanitized config templates and build descriptions to a private/offline staging area first. Exclude all `/data`, `options.json`, session/cookie/token data, SQL databases, archive data, logs, backups, runtime artifacts, real login emails, MQTT credentials, meter EAN/IDs and other private identifiers.
3. Perform **full-content and commit-history** secret scans before any push, not just filename filters. Use a restrictive allowlist. Preserve original upstream LICENSE.
4. Compare each local file/function with upstream `main`, Honza `main`, and PR #18. Record its provenance (upstream / Honza existing / locally unique / environment-specific).
5. Import a sanitized local source snapshot into `integration/local-0.4.8` **only after review**. Do not rewrite fork `main` or use the integration branch as base for upstream PRs.
6. Each upstream PR branches independently from upstream `main`, or an agreed newer upstream base, and contains one change, tests, migration/compatibility note and no private dependencies.
7. Never modify the running HA add-on as a side effect of source import.

### PR candidate matrix

| PR candidate | Classification / plan | Dependency and tests |
|---|---|---|
| `fix/mqtt-loop` | Locally patched; Honza PR #18 implements stronger reconnect + replay already. Avoid duplicate full implementation. | Transport ACK, keepalive, reconnect, shutdown, retain and LWT |
| `fix/reserved-power-rv` | In local patch **and** Honza PR #18; candidate for cherry-picked standalone metadata fix only if maintainer prefers small PRs. | Unit in kW, device_class=power, historical key unchanged |
| `fix/reactive-units` | In local patch **and** Honza PR #18. | Four Ri/Rc channels in kvar, values not rescaled |
| `fix/hdo-discovery-compat` | In local patch **and** Honza PR #18. | Existing HDO sensor identity preserved; valid discovery |
| `fix/hdo-token-diagnostics` | **Open / not solved by PR #18.** | Playwright TimeoutError; safe diagnostics and error isolation |
| `fix/hdo-token-acquisition` | **Open / actual root cause not determined.** | Auth context, route, token location, HDO success/failure regression |
| `feat/external-mqtt` | Local 0.4.8 extension; audit not yet done. Honza uses Supervisor MQTT resolution, so preserve both options. | Explicit external overrides, default Supervisor behavior, credential secrecy |
| `feat/pnd-archive` | Local 0.4.8 extension; audit not yet done. | SQLite v15m import/export, quality/ambiguity, end-of-interval timestamp, meter changes, DST, backfill idempotence |
| Other local changes | Unknown until full code audit. | No speculative copying into PRs |

### Upgrade compatibility warning

Honza PR #18 changes MQTT availability from per-meter `cez_pnd/{meter_id}/availability` to shared `cez_pnd/availability`. The operating v0.4.8 installation uses per-meter availability and a stable HDO sensor unique ID. **No broker migration, retained MQTT deletion or side-by-side deployment may occur without a dedicated impact review and separate approval.**

### Completion criteria

- A reviewed, sanitized, source-only local v0.4.8 reference is available.
- The local-to-upstream difference matrix is complete, with dependencies and overlap with Honza PR #18.
- Independent tests pass for each PR candidate.
- No public history contains secrets or private measured data.
- The operating add-on stays unchanged during repository setup and review.

## Useful upstream links

- [Honza PR #5: MQTT recovery and upgrade compatibility](https://github.com/honza-kasik/cez-pnd-data/pull/5) (merged in Honza's fork).
- [Honza PR #6: group HDO schedules by signal](https://github.com/honza-kasik/cez-pnd-data/pull/6) (merged in Honza's fork).
- [Honza PR #3: classify unexpected PND HTML](https://github.com/honza-kasik/cez-pnd-data/pull/3) (merged in Honza's fork).
- [Upstream PR #18](https://github.com/Muriel2Horak/cez-pnd-data/pull/18) (open draft).
