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

## Historical fetch contract — draft PR #4 (2026-11-15)

- [Draft PR #4 — explicit historical PND fetch window](https://github.com/psidlo/cez-pnd-data/pull/4) is **independent**, based directly on upstream `main`. It contains 4 files: a small change to `PndFetcher.fetch_all`, a pure historical window function and two synthetic regression suites. It does **not** import or depend on archive core or backfill.
- Historical mode requests the chosen day and includes the next calendar day's 00:00 profile endpoint; the other assemblies remain bounded at 23:59. It preserves valid `hasData=False` results, disables inappropriate yesterday fallback and propagates errors for caller cooldown. The unmodified live/default path preserves the original window selection.
- Offline tests: **20/20 passed for historical window and mocked-browser fetching**, plus **20/20 from archive core + backfill** in the combined local test environment (Python 3.13); **40/40 synthetic tests passed**. Full GitHub Actions and Python 3.9–3.12 matrix not yet run. Tests ran against a locally adapted active fetcher; the published upstream-derived code needs its exact repository CI validation before upstream submission.
- **Dependency correction:** draft backfill PR #3 requires this historical interface, which is not present in upstream nor Honza's fork. The next optional HA wiring PR should be prepared only after the dependency is reconciled. PR #4 can be reviewed upstream independently.
- **Security:** Public source/tests use synthetic identifiers only; no real EAN, meter numbers, private IPs, cookies, tokens, raw API response dumps or database snapshots were added. Existing upstream fetcher logs unredacted response excerpts in some error cases; do not enable production historical fetching without a separate review of error-path privacy and retry/rejection handling.
- **Operations:** No HA add-on rebuild/restart/configuration change, no SQLite write, no inverter control changes. All GitHub PRs remain private-to-our-workflow drafts in a **public fork**, not submitted upstream.

## PND error-response privacy and rejection cooldown — draft PR #5 (2026-11-15)

- [Draft PR #5 — redact error responses and back off on portal rejection](https://github.com/psidlo/cez-pnd-data/pull/5) is **independent** against upstream `main`, not stacked onto archives or historical fetch.
- Public diff: 3 files (`addon/src/main.py`, `addon/src/pnd_response_safety.py`, `tests/test_pnd_response_privacy.py`). No source backup, production credentials, actual meter/EAN IDs, response bodies, network addresses or SQLite file was committed.
- It removes logging of untrusted HTTP response bodies, raw Content-Type and JSON parsing exception details. Error classification uses fixed labels: `portal-rejection`, `login-page`, `maintenance`, `other-html`. HTTP 403/429 and recognized HTML WAF rejection trigger `PndRequestRejected` and a 12-hour **in-process only** cooldown. A rejection immediately aborts the assembly batch and fallback, while non-rejection assembly failures remain best-effort; successful JSON remains compatible.
- Offline local tests with synthetic mocked responses: **12 passed**. Validated error privacy, status classification, batch early-abort, cooldown and normal JSON. **GitHub Actions: no runs observed; full upstream CI and exact published source test are outstanding.**
- The patch fixes response-error logging only, not all potential PII in pre-existing startup logs or other code paths; a separate application-wide logging review is warranted before deployment.
- Neither PR #5 nor PR #4, #3, #2, #1 has been deployed or submitted upstream. Running HA add-on, databases, MQTT, Predbat and SolaX untouched.
- Follow-up: compatibility review between #5 and #4, then optional HA runtime wiring as its own PR, only after tests. The actual DIP HDO token-acquisition root cause still requires a separately approved redacted live diagnosis.

## Whole-project logging privacy audit and remediation (2026-11-15)

An audit compared the user's **private** local 0.4.8 source backup, upstream `main` and Honza's fork. Only the following **sanitized source/test modifications** are published, never private backups or operational configurations.

| Independently reviewable change | Public fork draft PR | Findings and bounds |
|---|---|---|
| PND HTTP response error diagnostics + portal rejection cooldown | [#5](https://github.com/psidlo/cez-pnd-data/pull/5) | Raw HTML/JSON error bodies and parsing exception text were logged; replaced with fixed response categories and in-process 12-hour backoff (403/429 and recognized portal rejection). |
| Startup / login / shell diagnostics | [#6](https://github.com/psidlo/cez-pnd-data/pull/6) | Default INFO included account email, meter ID, partially masked EAN and broker endpoint. Replaced with account-configured indicator, meter count, and no endpoint. Shell options parsing errors also redacted. |
| Runtime orchestrator error handling | [#7](https://github.com/psidlo/cez-pnd-data/pull/7) | WARNING/ERROR reported meter IDs, Playwright and API exceptions, and an auth traceback. Now logs safe status codes and counts only. An indentation regression caught on review was fixed. |
| MQTT state / discovery / HDO parser | [#8](https://github.com/psidlo/cez-pnd-data/pull/8) | DEBUG logs contained full MQTT topics, sensor values, HDO signal details; HDO parser echoed malformed remote fields. Only fixed diagnostic texts remain; MQTT payloads/topics are unchanged. |
| DIP/HDO exception propagation | [#9](https://github.com/psidlo/cez-pnd-data/pull/9) | Generic `DipFetchError` included raw browser exception strings, potentially EAN/URL/token; now fixed text, suppressed exception chain and type-checked HTTP status. |
| **Previously missed archive-core logging** | [#2](https://github.com/psidlo/cez-pnd-data/pull/2) updated | SQLite archive logged requested and response-observed meter IDs on profile mismatch, even though no static private data were uploaded. Redacted those logs and added two regression tests; **9/9 isolated archive tests passed** on a matching sanitized local copy. |
| HDO safe diagnostic compatibility | [#1](https://github.com/psidlo/cez-pnd-data/pull/1) updated | Safe, allowlisted browser-state category is now logged directly at DIP on token timeout, so #7 suppression of arbitrary exception text does not remove it. Raw Playwright exception chaining is suppressed. Real HDO token acquisition remains unresolved. |

**Audited source areas:** `auth.py`, `main.py`, `orchestrator.py`, `mqtt_publisher.py`, `dip_client.py`, `hdo_parser.py`, `session_manager.py`, `parser.py`, `cookie_utils.py`, `run.sh`, `archive.py` and `archive_backfill.py`. The latter backfill module's newly added log messages are fixed strings, not raw exception or identity values. Other code still needs a full dynamic integration and logging test before production use.

**Verification and safety gates**
- All nine PRs are **OPEN DRAFT**, against the owner's fork; the original upstream repo and our `main` remain unchanged.
- Local isolated checks passed for archive core (9 tests), HDO generic exception sanitizer (2 checks), startup/shell privacy smoke, and MQTT/HDO privacy smoke. Other new regression tests exist in the PR branches but **the exact GitHub branch combinations and upstream CI have not been executed**. Never claim end-to-end CI success from isolated tests.
- The archive backfill PR #3 was forked before the two archive-privacy commits on its base #2. The branches are now diverged; #3's PR diff still shows **only the two intended files**, but the stack must be rebased/updated and retested before merge. Do not discard or force-update unreviewed history.
- **Known integration risks:** #1 safe HDO categories must survive #7 log redaction; #4 historical fetch and #5 PND rejection handling modify overlapping areas of `main.py`; #2–#3 archiving must be combined with #4 before runtime wiring. Test combined behavior and rollback before any deployment.
- No raw log output, cookies, credentials, private meter/EAN IDs, home network addresses, live SQLite files or private source backup were committed. The running HA addon and FVE controls were not changed.
- Further work: static code/format checks on exact GitHub branches, synthetic end-to-end compatibility suite, then optional archive runtime wiring as a new separate PR; real HDO diagnosis requires explicit, reversible deployment approval.

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


## Verified PR dependency integration (2026-11-15)

**Goal:** verify contracts without merging or deploying the independent upstreamable changes.

1. **Backfill stack #3 → #2:** Reconstructed the backfill branch from the latest privacy-reviewed archive-core tree and the original, hash-verified two backfill blobs. A force-with-lease ref update checked the previous head SHA. The new backfill head is `a78347479e63901ea4379ad811bcc0700e19d37b`, directly one commit ahead of archive-core head `44142a1b51122ca667914f74f79e3e582d4f3f6f`. The PR diff remains **only 2 intended backfill files** and no previously published code was lost.
2. **HDO #1 + #7 + #9:** Temporary, fork-only [integration/hdo-privacy-compat](https://github.com/psidlo/cez-pnd-data/tree/integration/hdo-privacy-compat) combines safe timeout browser categories, the orchestrator error redaction, and the generic DIP exception sanitizer. Synthetic local Playwright mock tests (8) passed, confirming privacy-safe diagnostics without original URLs, EAN/token markers or raw exceptions. The underlying HDO token-acquisition problem remains unresolved and has not been tested live.
3. **PND historical API #4 + response safety #5:** Temporary, fork-only [integration/pnd-history-rejection-compat](https://github.com/psidlo/cez-pnd-data/tree/integration/pnd-history-rejection-compat) preserves the original historical calendar-day API while adding explicit HTTP rejection handling. A **missing comma in the originally published PR #4 error-logging statement was found and fixed** in the original independent PR before rebuilding this combination. The original #5 also had a no-data warning containing a meter identifier; this has been redacted in #5 and the integration branch.
4. **Warmup rejection gap:** During integration review, the warmup POST was found to swallow HTTP 403/429 and permit further PND requests. PR #5 and the PND integration branch now start backoff and abort directly on warmup 403/429. Two synthetic cases for historical mode were added and passed locally. The cooldown remains process-local (not persisted across a restart).
5. **Offline validation:** The locally staged/sanitized representative source suites passed **67 tests** in total: PND historical/rejection compatibility 25, PND privacy 12, HDO diagnostics/privacy 8, archive core/privacy 9, backfill 13. These were run with mocked browser/network and synthetically generated meter data, **not live CEZ**. The exact published GitHub branch source and all original upstream tests have **not yet been run in a verified GitHub Actions matrix**. Treat combined behavior as provisionally validated, not merge-ready.
6. **Safety and next gate:** None of the integration branches contain local config, actual meters/EANs, household IPs, credentials, cookies or database contents. The original individual PRs remain draft and independent; both integration branches are test-only, no upstream PRs or main merges. Before optional runtime wiring or live HDO diagnosis, run exact-code CI, review timeouts and session behavior, and obtain explicit deployment approval.



## GitHub Actions offline CI actually executed (2026-11-15)

- [Draft PR #10](https://github.com/psidlo/cez-pnd-data/pull/10): isolated fork CI workflow with `contents: read`, non-persistent GitHub credentials, no CEZ/HA secrets and `pytest-socket` blocking external sockets but allowing asyncio's local Unix sockets. Runner pinned to Ubuntu 24.04 to support Python 3.9. Runs were **actually triggered and verified**, not inferred.
- [Base CI run #43709255086](https://github.com/psidlo/cez-pnd-data/actions/runs/43709255086): all Python 3.9/3.11/3.12/3.13 jobs PASS; 341 tests on 3.13.
- [HDO #1 + #7 + #9 run #43709274324](https://github.com/psidlo/cez-pnd-data/actions/runs/43709274324): all four Python versions PASS; 355 tests on 3.13.
- [Archive #2 + backfill #3 run #43709296793](https://github.com/psidlo/cez-pnd-data/actions/runs/43709296793): all four versions PASS; 363 tests on 3.13.
- [Historical PND #4 + rejection #5 run #43709452450](https://github.com/psidlo/cez-pnd-data/actions/runs/43709452450): all four versions PASS; 377 tests on 3.13. The first attempt exposed an improper test helper import, fixed on the integration branch and then rerun successfully.
- The **original, upstream-inherited** `.github/workflows/ci.yml` also ran on PR #10, and **remains failing overall**. Verified issues: no Python 3.9 on Ubuntu 26.04, unresolved `aquasecurity/trivy-action@0.28.0`, Black formatting of pre-existing files, and pip-audit. Its Python 3.10/3.11/3.12 test jobs and secret/SAST jobs passed. Do not claim upstream-original CI is green. Fix that larger workflow separately before promoting drafts.
- All source and test files are from the public fork with synthetic fixtures; no HA file-system access, real CEZ API, FVE database or private account data. The live add-on has not been modified.


## Original upstream CI repaired in one narrow draft PR (2026-11-15)

- [PR #11 — repair inherited CI](https://github.com/psidlo/cez-pnd-data/pull/11) created as **one 3-file draft** on clean `main`, not split into further issues/PRs. It pins `ubuntu-24.04` to restore Python 3.9, references the valid Trivy action `v0.36.0`, scopes `pip-audit` and Safety to **runtime dependencies** in `addon/requirements.txt`, applies mechanical Black formatting in `auth.py` and `test_e2e_smoke.py`, and removes one unused test import.
- Actual [GitHub Actions run #43711291526](https://github.com/psidlo/cez-pnd-data/actions/runs/43711291526), commit `4f96d70664cbf94758880865bf7372dba3f5c154`: **success**, including Python 3.9/3.10/3.11/3.12 with coverage, lint, secret scanning, SAST, dependency-audit job, Docker/Trivy build and SBOM.
- Ruff was restricted to blocking `E4,E7,E9,F` to avoid a large refactor of 108 pre-existing broad style/modernization findings. Broader Ruff compliance is **not implied**. Dependency-audit `continue-on-error` remains an inherited advisory policy; a green job is not a claim that all dependencies are vulnerability-free. No real meter, EAN, API response or credentials were added.
- User explicitly wants to prevent unbounded project growth. **Stop creating infrastructure PRs**; focus on review/consolidation of existing drafts and only independently useful upstream contributions. The original addon 0.4.8/HA and FVE controls remain untouched.


## Privacy PR consolidation and opt-in runtime preview (2026-11-15)

- The user approved reducing PR overhead. Consolidated former privacy drafts **#7, #8 and #9** into the existing [draft PR #6](https://github.com/psidlo/cez-pnd-data/pull/6). The original reviewed file blobs and synthetic tests were copied into #6, and the exact result passed [offline CI #43712786912](https://github.com/psidlo/cez-pnd-data/actions/runs/43712786912) across Python 3.9, 3.11, 3.12 and 3.13. Closed #7/#8/#9 as superseded, **not merged**, preserving Git history.
- Closed redundant fork-only [PR #10](https://github.com/psidlo/cez-pnd-data/pull/10); the inherited CI was successfully fixed and tested in open [draft PR #11](https://github.com/psidlo/cez-pnd-data/pull/11). **Seven** draft PRs now remain open (#1–#6, #11), none merged to `main` or upstream.
- Without opening a further PR, assembled a **test-only** [integration/archive-runtime-validation](https://github.com/psidlo/cez-pnd-data/tree/integration/archive-runtime-validation) branch: current archive-core #2, rebased backfill #3, historical fetch #4, request rejection #5, consolidated privacy #6, and the no-secrets offline CI workflow. Added a disabled-by-default archive cycle hook and add-on options. Current `main` and running local HA 0.4.8 remain unchanged.
- The preview uses the same authenticated PND client/session for live reads and historical reads, caps archive requests **globally per poll cycle**, and treats archive failures as nonfatal for normal MQTT publishing. With `archive_enabled=false` (the default) the archive store is never created.
- **Critical data-safety correction:** The upstream `ean` configuration field cannot be assumed to be both import and export EAN. The preview now reads separately stored import/export EAN from `meter_metadata`; on conflict or missing metadata, it fails closed unless *both* archive-specific EANs are explicitly supplied. Never use a guessed/blank export EAN to overwrite an existing SQLite row.
- Read-only Home Assistant SQL (no write, no private value retrieved): production `pnd_combined_15m` SQL matches exactly the archive module's recognized **legacy** view expression, and all 2 `meter_metadata` rows have both import and export EAN populated. This supports—but does not substitute for—backup/rollback and user approval before any live view migration.
- Runtime preview uses the existing private path `/share/cez_pnd/measurements.sqlite3` only **after explicit enablement**. Add-on option and compatibility/version upgrade design still requires a separate final review, especially multi-meter history and a production backup. No production migration or archive SQL write was performed.
- **Gate:** verify exact GitHub Actions on the complete integration preview (including tests for disabled state, bounded work, portal rejection, failed archives and EAN-metadata preservation) before deciding whether it belongs in an existing upstream PR stack. No new production or upstream PR has been opened.



## Optional archive integration CI and legacy-schema verification (2026-11-15)

- The combined [integration/archive-runtime-validation](https://github.com/psidlo/cez-pnd-data/tree/integration/archive-runtime-validation) preview now adds optional archive wiring (off by default), an aggregate-per-cycle backfill budget, an archive callback isolated from MQTT/live polling, safe shutdown, and synthetic regression tests. **No extra PR** has been opened, and this code is not deployed.
- **Exact full offline GitHub CI passed:** [run #43713449978](https://github.com/psidlo/cez-pnd-data/actions/runs/43713449978) is `success` for Python **3.9/3.11/3.12/3.13**; 429 synthetic tests passed on Python 3.13, with external network sockets disabled. The run includes all previous archives, backfill, privacy, PND history/rejection and new archive runtime tests.
- Critical metadata protection: only the previously stored `meter_metadata.import_ean/export_ean` pair or **both** explicit `archive_import_ean` and `archive_export_ean` in electrometer JSON may be used. A generic supply `ean` is **never guessed** to be import/export EAN. Conflicting or unknown mapping skips that meter without changing metadata; tests assert no private identifiers enter logs.
- Read-only HA SQL verification of `/share/cez_pnd/measurements.sqlite3`: existing `pnd_combined_15m` definition exactly matches the known legacy view recognized by the archive-core's guarded migration; all **four relevant tables have the expected source columns**, and both meter-metadata rows have nonempty import and export EANs. No sensitive EAN values were retrieved or written, no database modification occurred.
- Runtime enablement is opt-in via add-on options `archive_enabled=false` (default), `archive_start_date` and `archive_max_days_per_cycle` (1 default, valid 1–62). DB remains at `/share/cez_pnd/measurements.sqlite3` only when enabled; no automatic migration with default settings.
- **Remaining release gate:** version/migration review against the running local 0.4.8 add-on, backup and rollback of SQLite and add-on, verification of meter configuration (including older replacement meters), and explicit user consent before enabling archive or changing HA. Synthetic CI cannot validate the authenticated CEZ production flow or a live database migration. Do not merge the integration preview into the public main or claim it is production-ready until these gates are met.



## Local 0.4.8-to-fork compatibility check (2026-11-15)

### What was actually compared

- **Local source**: the user's private `cez_pnd_external_261115.tar.gz` (`addons/cez_pnd_external`, version **0.4.8**). The archive's current 9 key source/config files were byte-matched against the previously staged private source copy; local secrets never entered the public repository.
- **Installed HA Supervisor add-on (read-only)**: `local_cez-pnd-external`, version 0.4.8, **started**, boot auto. The live option names were checked without displaying email, password, EAN, meter IDs, broker host or broker credentials. This validates installed version/configuration, **not** a cryptographic hash of the running files inside `/addons` (which HA MCP cannot read).
- **Fork under test**: `integration/archive-runtime-validation`, containing #2/#3/#4/#5/#6 plus the opt-in archive runtime. No add-on installation, MQTT publication, HA configuration mutation or actual PND request.

### Compatibility matrix and implementation

| Surface | Existing private local 0.4.8 | Fork integration resolution | Migration action |
|---|---|---|---|
| Add-on identity/version | Local slug `cez-pnd-external`, displayed version `0.4.8` | Public upstream slug `cez-pnd`, baseline `0.4.1` | **Do not install the public add-on beside the existing one.** Keep the existing local slug/HA add-on identity, create a tested local 0.4.8→next-version overlay. Preserve the live boot setting (`auto`) instead of blindly copying archived `config.yaml` (`manual`). |
| MQTT transport | Dedicated **external** MQTT broker; `mqtt_host`, `mqtt_port`, `mqtt_user`, `mqtt_password` | Run script now honors these legacy keys before Supervisor MQTT environment; broker host/credentials are never printed. Add-on service requirement is `mqtt:want` (not `mqtt:need`). | Retain all four existing options in the private HA configuration; test connectivity and matching retained topics **before** enabling the replacement add-on. Never commit actual values. |
| MQTT Discovery identity | `cez_pnd_{meter}_{sensor}`, device identifier `cez_pnd_{meter}`, per-meter availability `cez_pnd/{meter}/availability`, state `cez_pnd/{meter}/{key}/state` | Identical topic and unique-ID templates in the combined source; existing per-meter availability is preserved (not the shared availability variant proposed elsewhere). | No HA entity recreation or rename planned; check existing entity IDs, discovery state and availability before/after. Never run original and replacement in parallel against the same broker. |
| Meter selection | Separate MQTT electrometer list (currently one meter) and `archive_meter_ids` (currently two, including a predecessor) | Archive reads validated `archive_meter_ids` independently from MQTT list. No additional sensor/device is published for archive-only meters. | Keep both lists distinct, preserve the older meter's historical data and verify per-meter archive counts/gaps after migration. |
| Archive controls | `archive_start_date`, `archive_days_per_cycle` (current setting 50); archive currently enabled implicitly by start date | Preserves legacy option names and supports explicit `archive_enabled` **default false**. Shared historical-request budget across all archived meters, max 62 per cycle. | Add `archive_enabled` to the local schema; leave it false until an approved controlled cutover. Explicitly set it to true only after checking metadata and backup. For first live test **propose 1–2 days/cycle**, not silently carrying over 50; coordinate this intentional reduction with user. |
| Separate supply EAN | `import_ean` and `export_ean` plus a generic MQTT `ean` | Legacy `import_ean/export_ean` are passed to the archive selector; persisted per-meter metadata is authoritative. An unknown or conflicting pair stops that meter's archive attempts. A generic `ean` is **never** guessed to represent both directions. | Keep existing two separate EAN options private. Confirm compatibility with existing `meter_metadata` before enabling; never overwrite valid data with blank strings. |
| SQLite/15-minute energy | Existing file `/share/cez_pnd/measurements.sqlite3`, view `pnd_combined_15m` | Same private DB path. Read-only inspection showed the view is byte-equivalent after SQL whitespace normalization to the migration's **known legacy** expression, and all four source tables have required columns. Both meter metadata rows have separate populated EAN. | Back up DB **with WAL consistency** before any add-on change. Guarded view upgrade only when archive enabled; do not replace unknown schema and do not replace missing measurements with zero. |
| CEZ rejection backoff | Existing local orchestrator delays next poll after CEZ 403/429, up to the PND cooldown | Cooldown-aware polling is restored in fork runtime without exposing private exception strings. Abort backfill on rejection, preserve process-local 12-hour block. | Confirm by synthetic CI and a staged read-only status check; the cooldown resets on add-on restart, which remains an acknowledged limitation. |
| HDO | Local DIP client can miss Angular `dip-request-token` and render HDO unknown | Diagnostic safety changes only; real token-acquisition root cause is still **unresolved** | **Do not** promise HDO restoration. Verify existing HDO entities retain identity; separate approved diagnosis needed for the token. |
| Existing HA/Predbat downstream | MQTT-derived CEZ sensors, `pnd_combined_15m` SQL consumers, FVE economics | Public integration does not intentionally rename MQTT topics, DB path, view columns, price archive or Predbat/SolaX controls | **No changes expected** to Home Assistant MQTT entity references, price archive or Predbat. Verify representative sensors and SQL queries before/after; do not touch inverter control. |

### Explicit prerequisites for the controlled replacement

1. **Before any write:** refresh the local `/addons/cez_pnd_external` source hash/backup and Supervisor add-on options, because a matching **version** alone does not prove source bytes unchanged since the November 15 tarball. Avoid putting options or backup into public issues or CI.
2. Create **HA full/specific add-on backup** and a consistent SQLite backup/snapshot including WAL contents while the original is stopped, or use SQLite's `backup` API. Record pre-cutover measured 15-minute counts per meter, non-null import/export counts and any pre-existing gaps for an exact post-cutover comparison.
3. In a **private** local replacement, keep slug `cez-pnd-external`, existing add-on identity and HA state, and every historical MQTT/CEZ/archive option; add `archive_enabled` explicit bool default false, align source files and test the migration copy offline. Public GitHub `addon/config.yaml` is a generic upstream manifest **not a drop-in replacement** for the installed local manifest.
4. Start the replacement **alone**, verify that MQTT broker authentication succeeds, existing Discovery unique IDs/topics/sensors remain unchanged and the normal PND poll functions. Keep archive disabled during this first verification.
5. With **explicit user approval**, enable archive at a deliberately low per-cycle budget (proposed 1–2), verify the guarded SQLite view migration and metadata consistency, check gaps/end-of-interval quality and gradual historical backfill. Only then consider increasing budget; local 50/cycle on the initial combined implementation could delay the 15-minute poll and provoke portal rejection.
6. **Rollback trigger:** MQTT disconnect, unexpected topic/unique-ID change, data-quality/view mismatch, invalid/ambiguous meter/EAN metadata, failed database integrity check or portal rejection bursts. Restore original 0.4.8 source/config and the database only if its schema/data were affected; avoid overwriting later successful metering data with an old DB file. Do not modify FVE control automations.

**Status:** migration implementation is **preview-only in the GitHub integration branch**. No extra PR, no upstream submission and no live activation. User approval is required before any local file edit, add-on stop/restart, DB change or migration test using the real portal.
