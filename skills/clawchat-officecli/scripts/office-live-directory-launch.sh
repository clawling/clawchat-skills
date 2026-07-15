#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-26316}"
case "$PORT" in
  ''|*[!0-9]*) echo "office directory: PORT must be an integer from 1 to 65535." >&2; exit 1 ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "office directory: PORT must be an integer from 1 to 65535." >&2
  exit 1
fi

export OFFICE_DIRECTORY_PORT="$PORT"
exec bash "${SCRIPT_DIR}/office-liveware-server-only.sh"
