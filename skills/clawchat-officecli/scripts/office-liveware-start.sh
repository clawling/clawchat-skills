#!/usr/bin/env bash
# Start the Office preview directory service and bind it through Liveware tunnel.

set -euo pipefail

PORT="${1:-26316}"
APP_ID="${OFFICE_APP_ID:-}"
HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
DEFAULT_LIVE_HOME="${HERMES_HOME}/workspace/office-live"
LIVE_HOME="${OFFICE_LIVE_HOME:-$DEFAULT_LIVE_HOME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${OFFICE_DIRECTORY_SCRIPT:-${SCRIPT_DIR}/office-live-directory.py}"
LIVEWARE_SETUP="${OFFICE_LIVEWARE_SETUP_SCRIPT:-${SCRIPT_DIR}/office-liveware-setup.py}"
LOG="${OFFICE_DIRECTORY_LOG:-${LIVE_HOME}/.state/directory.log}"
DOC_ROOTS="${OFFICE_DOC_ROOTS:-${LIVE_HOME}/documents}"
FIRST_DOC_ROOT="${DOC_ROOTS%%:*}"
STATE_DIR="$(dirname "$LOG")"
LIVEWARE_STATE_FILE="${OFFICE_LIVEWARE_STATE_FILE:-${LIVE_HOME}/.state/liveware.env}"
LIVEWARE_BIN="${LIVEWARE_BIN:-liveware}"
OFFICE_BIN="${OFFICE_BIN:-$(command -v officecli || true)}"
OFFICE_BIN="${OFFICE_BIN:-${HOME}/.local/bin/officecli}"
if [ ! -x "$OFFICE_BIN" ] && [ -x "${HERMES_HOME}/home/.local/bin/officecli" ]; then
  OFFICE_BIN="${HERMES_HOME}/home/.local/bin/officecli"
fi

mkdir -p "$STATE_DIR" "$FIRST_DOC_ROOT"

config_matches() {
  local config
  config="$(curl -fsS "http://127.0.0.1:${PORT}/api/config" 2>/dev/null || true)"
  if [ -z "$config" ]; then
    return 1
  fi
  CONFIG_JSON="$config" DOC_ROOTS="$DOC_ROOTS" LIVE_HOME="$LIVE_HOME" python3 -c '
import json
import os
from pathlib import Path

try:
    config = json.loads(os.environ["CONFIG_JSON"])
except Exception:
    raise SystemExit(1)

expected_roots = [str(Path(root).expanduser().resolve()) for root in os.environ["DOC_ROOTS"].split(":") if root]
expected_home = str(Path(os.environ["LIVE_HOME"]).expanduser().resolve())
if config.get("docRoots") == expected_roots and config.get("liveHome") == expected_home:
    raise SystemExit(0)
raise SystemExit(1)
'
}

stop_existing_directory() {
  local pid_file pid
  pid_file="${STATE_DIR}/directory.pid"
  if [ ! -f "$pid_file" ]; then
    return 1
  fi
  pid="$(sed -n '1p' "$pid_file" 2>/dev/null || true)"
  case "$pid" in
    ''|*[!0-9]*)
      return 1
      ;;
  esac
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      if ! kill -0 "$pid" 2>/dev/null; then
        return 0
      fi
      sleep 0.2
    done
  fi
  return 0
}

start_directory() {
  echo "Starting Office live directory on port ${PORT}..."
  OFFICE_BIN="$OFFICE_BIN" OFFICE_LIVE_HOME="$LIVE_HOME" OFFICE_DOC_ROOTS="$DOC_ROOTS" OFFICE_DIRECTORY_PORT="$PORT" nohup python3 "$SCRIPT" >"$LOG" 2>&1 &
  PID="$!"
  echo "$PID" >"${STATE_DIR}/directory.pid"
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
      break
    fi
    sleep 0.25
  done
}

HEALTH="$(curl -fsS "http://127.0.0.1:${PORT}/healthz" 2>/dev/null || true)"

if [ "$HEALTH" = "ok" ]; then
  if config_matches; then
    echo "Directory already running at http://127.0.0.1:${PORT}"
  else
    echo "Directory on port ${PORT} has stale configuration; restarting..."
    if ! stop_existing_directory; then
      echo "Port ${PORT} is already used by a service that cannot be restarted by this launcher." >&2
      exit 1
    fi
    start_directory
  fi
elif [ -n "$HEALTH" ]; then
  echo "Port ${PORT} is already used by another service. Try a different directory port." >&2
  exit 1
else
  start_directory
fi

if [ "$(curl -fsS "http://127.0.0.1:${PORT}/healthz" 2>/dev/null || true)" != "ok" ]; then
  echo "Directory failed to start. Log: ${LOG}" >&2
  exit 1
fi

if [ -z "$APP_ID" ] && [ -f "$LIVEWARE_STATE_FILE" ]; then
  # shellcheck disable=SC1090
  . "$LIVEWARE_STATE_FILE"
  APP_ID="${OFFICE_APP_ID:-}"
fi

if [ -z "$APP_ID" ]; then
  echo "No Liveware app id available. Run the setup script first, or set OFFICE_APP_ID." >&2
  exit 1
fi

echo "Binding Liveware app ${APP_ID} to http://127.0.0.1:${PORT}..."
"$LIVEWARE_BIN" tunnel bind "$APP_ID" "http://127.0.0.1:${PORT}" 2>&1 | tail -1
LIVEWARE_DOMAIN="${LIVEWARE_DOMAIN:-apps.clawling.io}"
echo "Public directory: https://${APP_ID}.${LIVEWARE_DOMAIN}"
