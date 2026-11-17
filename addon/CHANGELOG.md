# Changelog

## 0.4.9 — 2026-11-17

Consolidated fork release preparation, corresponding to the validated local
0.4.9 deployment. Versions 0.4.2–0.4.8 were local revisions; no separate public
release history is reconstructed for them.

### Fixed

- Keep MQTT connected with Paho's network loop, wait for CONNACK, restore retained discovery and availability after reconnect, and drain pending messages on shutdown.
- Initialize DIP dashboard authorization before opening HDO details; bootstrap and validate the request token without exposing tokens or private responses.
- Distinguish wrapped authorization failures from portal maintenance. Select the current Europe/Prague schedule and include a UTC offset in the next-switch timestamp.
- Preserve existing MQTT sensor domains, topics, unique IDs and last-known display values across null response rows. Remove invalid discovery classes without guessing a conversion for legacy Rv.
- Preserve normal completed-day PND queries and local polling compatibility. Reject unsafe/unknown archive view migrations and conflicting import/export metadata.
- Cancel polling and wake the idle asyncio selector on SIGTERM so MQTT, browser and archive cleanup completes.
- Suppress credentials, private response bodies and identifying configuration values in diagnostics.

### Added

- Opt-in SQLite history and bounded historical backfill, using explicit Prague calendar days and the final midnight endpoint.
- Independent published/archive meter selections, separate import/export EAN metadata and external MQTT broker options.
- Preserve raw measurements, qualities, missing intervals and existing valid rows when a refreshed profile is incomplete. Never fill archive gaps with zero.
- Bounded request-rejection handling and process-local cooldown.
- Consolidated offline CI on Python 3.9–3.13, coverage, lint/types, secrets/SAST, dependency checks, container checks and SBOM.

### Validation and compatibility

- Runtime commit `9f2487d79ce30ae47899702bb6ccf753c3ef62e5`: 486 tests, 87.77% coverage; all jobs passed in [CI #44041527135](https://github.com/psidlo/cez-pnd-data/actions/runs/44041527135).
- Local 0.4.9 deployment verified source hashes, backup/migration on a copy, database integrity and preservation, HDO, stable MQTT beyond three keepalive periods, app restart and a real archive cycle.
- Public manifest retains slug `cez-pnd`; an existing `cez-pnd-external` installation needs the documented local overlay to preserve its identity and private options.
- Archive remains disabled by default. Start with a small global backfill budget.
- Cooldown resets on restart; LWT covers the first published meter; daily registers can remain unknown; legacy Rv interpretation remains unverified. A shared-broker outage was not forced in production.
- Security audit jobs retain their inherited advisory status; successful CI does not establish vulnerability-free dependencies.

See [release notes](../docs/releases/0.4.9.md), [migration/rollback](../docs/pnd-consolidated-migration.md) and [acceptance checks](../docs/pnd-open-items.md).

## 0.4.1

- **Fix HDO session lifecycle bug** — `ensure_session()` now triggers re-login when session cookies are valid but no live browser context exists (fresh process start). Previously returned cookies-only session, causing HDO to silently fail with `[HDO_FETCH_ERROR] No live browser context available for HDO`.

## 0.4.0

- **Fix HDO DIP_MAINTENANCE false positive** — HDO sensors now publish real data instead of falsely reporting maintenance.
- Rewrite `DipClient` to page-based fetch using `page.evaluate(fetch())` with `X-Request-Token` from localStorage.
  - Old approach used `context.request.get()` which runs HTTP outside browser context → gets 401 Unauthorized.
  - New approach executes fetch inside the authenticated browser page → proper session cookies and token.
- Fix `BrowserContext.is_closed()` → `.closed` property across auth.py, session_manager.py, and mocks.
- Auth lifecycle refactor: browser context persists after login for reuse by DipClient.
- Orchestrator: pass authenticated context to HDO fetch, dead context detection with automatic re-auth.
- Remove `PlaywrightHdoFetcher` wrapper — DipClient wired directly in main.py.
- Add `auth_client.close()` to shutdown cleanup.
- Handle Python 3.9/3.10 `asyncio.TimeoutError` compatibility (not a subclass of builtin `TimeoutError` before 3.11).

## 0.2.0

- **BREAKING: Playwright-only PND Runtime Migration** - Removed HTTP PND client path entirely; PND data now fetched exclusively via Playwright browser automation with WAF warmup flow.
- Harden Playwright fetch contract with explicit error handling:
  - Add `PndFetchError` exception for non-200 responses from PND API.
  - Detect 302 redirects as expired sessions (raises `SessionExpiredError`).
- Detect DIP maintenance mode:
  - Detect HTML content-type responses from DIP API (indicates maintenance page).
  - Add `DipMaintenanceError` for 400/503 responses from DIP endpoints.
- Wire production runtime to Playwright-only fetch:
  - All PND assembly fetches now use `PndFetcher` with WAF warmup + form-encoded POST.
  - HTTP/aiohttp `PndClient` class removed entirely (18 HTTP path tests deleted).
- Enhance orchestrator outage handling with new log markers:
  - Rename `SESSION_EXPIRED_ERROR` → `SESSION_EXPIRED`.
  - Add `PORTAL_MAINTENANCE` for CEZ portal-wide outages (login page as maintenance).
  - Add `DIP_MAINTENANCE` for DIP API endpoint outages (400/503 or HTML responses).
  - Add `HDO_TOKEN_ERROR` for DIP token fetch failures.
- Outage-safe cycle behavior:
  - `PORTAL_MAINTENANCE` skips entire polling cycle (PND + HDO).
  - `DIP_MAINTENANCE` / `HDO_TOKEN_ERROR` / `HDO_FETCH_ERROR` skip only HDO data, PND continues.
  - `SESSION_EXPIRED` (WARNING) triggers auto-reauth and retry, cycle continues.
  - `SESSION_EXPIRED` (ERROR) aborts current cycle, next cycle will retry.

## 0.1.6

- Fix PND assembly fetch calls by always passing required `electrometer_id`.
- Improve multi-electrometer polling by fetching assemblies per configured meter.
- Detect DIP maintenance mode and log as maintenance warning instead of generic auth/fetch failures.

## 0.1.5

- Add detailed logging for Playwright authentication to diagnose login failures.
- Log exception details when auth fails instead of generic error message.

## 0.1.4

- Fix Python module import error by running as `python3 -m src.main` instead of direct file execution.
- Add local testing script (`scripts/test-local.sh`) for pre-deploy verification.

## 0.1.2

- Fix startup reliability by ensuring `bash` is installed in the add-on image.
- Run add-on as root so startup can read `/data/options.json` provided by Home Assistant.
- Add explicit startup error for unreadable `/data/options.json` instead of repeated warnings.

## 0.1.1

- Fix add-on startup crash on Home Assistant (`/run.sh` execution failed).
- Replace `with-bashio` shebang with standard bash entrypoint compatible with current image.
- Read add-on options from `/data/options.json` in startup script.
- Keep MQTT connection settings from Supervisor-provided environment variables.

## 0.1.0

- Initial release.
