#!/usr/bin/env bash

set -euo pipefail

# HA Supervisor CEZ PND Add-on Startup Script
OPTIONS_FILE="/data/options.json"

if [[ -e "$OPTIONS_FILE" && ! -r "$OPTIONS_FILE" ]]; then
    echo "Error: Cannot read $OPTIONS_FILE (permission denied)." >&2
    echo "Please restart add-on with corrected permissions or reinstall the add-on." >&2
    exit 1
fi

read_option() {
    local key="$1"
    local default_value="${2:-}"

    if [[ -f "$OPTIONS_FILE" ]]; then
        python3 - "$OPTIONS_FILE" "$key" "$default_value" <<'PY'
import json
import sys

path, key, default = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    value = data.get(key, default)
    if value is None:
        value = default
    if isinstance(value, (dict, list)):
        print(json.dumps(value, separators=(",", ":")))
    else:
        print(str(value))
except json.JSONDecodeError as e:
    sys.stderr.write("Warning: Invalid add-on options JSON (details suppressed)\n")
    print(default)
except Exception as e:
    sys.stderr.write("Warning: Add-on options read error (details suppressed)\n")
    print(default)
PY
    else
        printf "%s" "$default_value"
    fi
}

export CEZ_EMAIL="$(read_option email "")"
export CEZ_PASSWORD="$(read_option password "")"
export CEZ_ELECTROMETER_ID="$(read_option electrometer_id "")"
export CEZ_EAN="$(read_option ean "")"
export CEZ_ELECTROMETERS="$(read_option electrometers "[]")"
export CEZ_ARCHIVE_ENABLED="$(read_option archive_enabled "false")"
export CEZ_ARCHIVE_START_DATE="$(read_option archive_start_date "")"
export CEZ_ARCHIVE_MAX_DAYS="$(read_option archive_days_per_cycle "1")"
export CEZ_ARCHIVE_METER_IDS="$(read_option archive_meter_ids "[]")"
export CEZ_IMPORT_EAN="$(read_option import_ean "")"
export CEZ_EXPORT_EAN="$(read_option export_ean "")"

# Legacy local external-MQTT configuration takes precedence when populated.
# Do not echo broker addresses, usernames or credentials to diagnostics.
configured_mqtt_host="$(read_option mqtt_host "")"
configured_mqtt_port="$(read_option mqtt_port "")"
configured_mqtt_user="$(read_option mqtt_user "")"
configured_mqtt_password="$(read_option mqtt_password "")"
export MQTT_HOST="${configured_mqtt_host:-${MQTT_HOST:-core-mosquitto}}"
export MQTT_PORT="${configured_mqtt_port:-${MQTT_PORT:-1883}}"
export MQTT_USER="${configured_mqtt_user:-${MQTT_USER:-}}"
export MQTT_PASSWORD="${configured_mqtt_password:-${MQTT_PASSWORD:-}}"

if [[ -z "${CEZ_EMAIL}" || -z "${CEZ_PASSWORD}" ]]; then
    echo "Error: Missing required add-on options 'email' or 'password'." >&2
    echo "Please fill them in Home Assistant add-on configuration." >&2
    exit 1
fi

wait_for_mqtt() {
    local max_attempts=30
    local attempt=1
    local sleep_seconds=2

    echo "Waiting for configured MQTT broker..."
    while (( attempt <= max_attempts )); do
        if python3 - "$MQTT_HOST" "$MQTT_PORT" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

try:
    with socket.create_connection((host, port), timeout=2):
        pass
except OSError:
    raise SystemExit(1)

raise SystemExit(0)
PY
        then
            echo "MQTT broker is available."
            return 0
        fi
        echo "MQTT not available yet (attempt ${attempt}/${max_attempts}), retrying in ${sleep_seconds}s..."
        attempt=$((attempt + 1))
        sleep "${sleep_seconds}"
    done

    echo "Error: Configured MQTT broker did not become available in time." >&2
    return 1
}

echo "Starting CEZ PND add-on..."
echo "Configuration loaded. Sensitive details are not printed to logs."
echo "MQTT configuration loaded (source details suppressed)."

wait_for_mqtt

echo "Starting main application..."
cd /app
exec python3 -m src.main
