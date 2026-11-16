"""Execute the actual browser token bootstrap against synthetic DIP contracts."""

import json
import shutil
import subprocess

import pytest

from addon.src.dip_client import TOKEN_BOOTSTRAP_JS

NODE = shutil.which("node")


def run_bootstrap(case):
    if not NODE:
        pytest.skip("Node is needed to execute the browser JavaScript contract")
    script = r"""
const vm = require('node:vm');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
let calls = [], timerCleared = false;
const sandbox = {
  window: {location: {origin: input.case.origin || 'https://dip.cezdistribuce.cz'}},
  localStorage: {getItem: () => {
    if (input.case.storageError) throw Error('SYNTHETIC_PRIVATE_STORAGE');
    return input.case.cached ?? null;
  }},
  AbortController,
  setTimeout: () => 1,
  clearTimeout: () => {timerCleared = true;},
  fetch: async (path, options) => {
    calls.push({path, credentials: options.credentials, redirect: options.redirect,
      cache: options.cache, hasSignal: Boolean(options.signal)});
    if (input.case.networkError) throw Error('SYNTHETIC_PRIVATE_RESPONSE');
    return {status: input.case.status ?? 200,
      headers: {get: () => input.case.contentType || 'application/json'},
      json: async () => {
        if (input.case.invalidJson) throw Error('SYNTHETIC_PRIVATE_JSON');
        return input.case.body;
      }};
  }
};
(async () => {
  const result = await vm.runInNewContext('(' + input.source + ')()', sandbox);
  process.stdout.write(JSON.stringify({result, calls, timerCleared}));
})();
"""
    result = subprocess.run(
        [NODE, "-e", script],
        input=json.dumps({"source": TOKEN_BOOTSTRAP_JS, "case": case}),
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "body",
    [
        {"data": "synthetic-token"},
        "synthetic-token",
        {"token": "synthetic-token"},
    ],
)
def test_absent_local_storage_bootstraps_portal_token_response(body):
    result = run_bootstrap({"body": body})
    assert result["result"] == "synthetic-token"
    assert result["calls"] == [
        {
            "path": "/irj/portal/rest-auth-api?path=/token/get",
            "credentials": "same-origin",
            "redirect": "error",
            "cache": "no-store",
            "hasSignal": True,
        }
    ]
    assert result["timerCleared"]


def test_valid_cached_token_retains_existing_no_request_behavior():
    result = run_bootstrap({"cached": "synthetic-cached-token"})
    assert result["result"] == "synthetic-cached-token"
    assert result["calls"] == []


@pytest.mark.parametrize("cached", ["", "null", "undefined", "[object Object]"])
def test_invalid_cached_value_is_replaced_by_explicit_bootstrap(cached):
    result = run_bootstrap({"cached": cached, "body": {"data": "synthetic-token"}})
    assert result["result"] == "synthetic-token"
    assert len(result["calls"]) == 1


def test_storage_access_exception_still_allows_endpoint_bootstrap():
    result = run_bootstrap({"storageError": True, "body": {"data": "synthetic-token"}})
    assert result["result"] == "synthetic-token"


@pytest.mark.parametrize(
    "case,failure",
    [
        ({"status": 401}, "http-error"),
        ({"status": 403}, "http-error"),
        ({"status": 429}, "http-error"),
        ({"status": 503}, "maintenance"),
        ({"contentType": "text/html"}, "non-json"),
        ({"invalidJson": True}, "request-failed"),
        ({"networkError": True}, "request-failed"),
        ({"body": {"data": {"unexpected": "SYNTHETIC_PRIVATE"}}}, "invalid-token"),
        ({"body": {"data": ""}}, "invalid-token"),
    ],
)
def test_rejection_login_html_and_bad_tokens_fail_closed_without_private_data(
    case, failure
):
    result = run_bootstrap(case)
    assert result["result"] == {"failure": failure}
    assert len(result["calls"]) == 1
    assert result["timerCleared"]
    assert "SYNTHETIC_PRIVATE" not in json.dumps(result)


def test_redirected_page_cannot_send_authenticated_token_requests():
    result = run_bootstrap({"origin": "https://example.invalid"})
    assert result["result"] == {"failure": "other-origin"}
    assert result["calls"] == []
