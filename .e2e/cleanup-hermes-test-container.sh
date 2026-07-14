#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TEST="${HERMES_TEST_DIR:-$ROOT/.e2e/hermes-test}"
CONTAINER="${HERMES_TEST_CONTAINER:-hermes-clawchat-skills-test}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not available in PATH" >&2
  exit 1
fi

echo "Removing test container if present: $CONTAINER"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

if [ -e "$TEST" ]; then
  echo "Removing test data directory: $TEST"
  chmod -R u+rwX "$TEST" 2>/dev/null || true
  rm -rf "$TEST"
else
  echo "Test data directory already absent: $TEST"
fi

echo "Cleanup complete. Hermes base data was preserved."
