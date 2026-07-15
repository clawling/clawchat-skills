#!/usr/bin/env bash
set -euo pipefail

PORT="${OFFICE_DIRECTORY_PORT:-26316}"
HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
LIVE_HOME="${OFFICE_LIVE_HOME:-${HERMES_HOME}/workspace/office-live}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${OFFICE_DIRECTORY_SCRIPT:-${SCRIPT_DIR}/office-live-directory.py}"
LOG="${OFFICE_DIRECTORY_LOG:-${LIVE_HOME}/.state/directory.log}"
DOC_ROOTS="${OFFICE_DOC_ROOTS:-${LIVE_HOME}/documents}"
FIRST_DOC_ROOT="${DOC_ROOTS%%:*}"
STATE_DIR="$(dirname "$LOG")"
OFFICE_BIN="${OFFICE_BIN:-$(command -v officecli || true)}"
OFFICE_BIN="${OFFICE_BIN:-${HOME}/.local/bin/officecli}"
if [ ! -x "$OFFICE_BIN" ] && [ -x "${HERMES_HOME}/home/.local/bin/officecli" ]; then
  OFFICE_BIN="${HERMES_HOME}/home/.local/bin/officecli"
fi

mkdir -p "$STATE_DIR" "$FIRST_DOC_ROOT"

config_matches() {
  local config
  config="$(curl -fsS "http://127.0.0.1:${PORT}/api/config" 2>/dev/null || true)"
  if [ -z "$config" ]; then return 1; fi
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
raise SystemExit(0 if config.get("docRoots") == expected_roots and config.get("liveHome") == expected_home else 1)
'
}

stop_existing_directory() {
  local pid_file pid
  pid_file="${STATE_DIR}/directory.pid"
  if [ ! -f "$pid_file" ]; then return 1; fi
  pid="$(sed -n '1p' "$pid_file" 2>/dev/null || true)"
  case "$pid" in ''|*[!0-9]*) return 1;; esac
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      if ! kill -0 "$pid" 2>/dev/null; then return 0; fi
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
    if curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then break; fi
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
