#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_HERMES_HOME="${HOME:-.}/.hermes"
HERMES_HOME="${HERMES_HOME:-$DEFAULT_HERMES_HOME}"
DATA_DIR="$HOME/personal-account-management"
BOOK="$DATA_DIR/account-book.json"
STATE_FILE="$DATA_DIR/liveware-dashboard.state.json"
HOST="127.0.0.1"
PORT="8765"
APP_NAME="${HERMES_ACCOUNT_LIVEWARE_APP_NAME:-Account Book}"
APP_NAME_SET=0
APP_ID=""
LIVEWARE_ARG=""
TIMEOUT_SECONDS=60

json_emit() {
  local status="$1" code="${2:-}" message="${3:-}" app_id="${4:-}" public_url="${5:-}"
  python3 - "$status" "$code" "$message" "$APP_NAME" "$BOOK" "http://$HOST:$PORT" "$app_id" "$public_url" "$STATE_FILE" <<'PY_JSON'
import json, sys
status, code, message, app_name, book, local_url, app_id, public_url, state_file = sys.argv[1:10]
payload = {"status": status, "app_name": app_name, "book": book, "local_url": local_url}
if code:
    payload["blocker"] = code
if message:
    payload["message"] = message
if app_id:
    payload["app_id"] = app_id
if public_url:
    payload["public_url"] = public_url
if state_file:
    payload["state_file"] = state_file
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY_JSON
}

# A positional app id is supported for the installed-skill startup path:
#   start_liveware.sh app-...
if [ "$#" -gt 0 ] && [[ "$1" != --* ]]; then
  APP_ID="$1"
  shift
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    --book) BOOK="${2:?missing --book value}"; shift 2 ;;
    --skill-dir) SKILL_DIR="${2:?missing --skill-dir value}"; SCRIPT_DIR="$SKILL_DIR/scripts"; shift 2 ;;
    --host) HOST="${2:?missing --host value}"; shift 2 ;;
    --port) PORT="${2:?missing --port value}"; shift 2 ;;
    --app-name) APP_NAME="${2:?missing --app-name value}"; APP_NAME_SET=1; shift 2 ;;
    --app-id) APP_ID="${2:?missing --app-id value}"; shift 2 ;;
    --state-file) STATE_FILE="${2:?missing --state-file value}"; shift 2 ;;
    --liveware) LIVEWARE_ARG="${2:?missing --liveware value}"; shift 2 ;;
    --timeout) TIMEOUT_SECONDS="${2:?missing --timeout value}"; shift 2 ;;
    *) json_emit blocked unknown_argument "$1"; exit 2 ;;
  esac
done

DATA_DIR="$(dirname "$BOOK")"
mkdir -p "$DATA_DIR"

state_value() {
  local key="$1"
  python3 - "$STATE_FILE" "$key" <<'PY_STATE'
from pathlib import Path
import json, sys
path, key = Path(sys.argv[1]), sys.argv[2]
if not path.exists():
    raise SystemExit(1)
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
value = data.get(key) if isinstance(data, dict) else None
if isinstance(value, str) and value.strip():
    print(value.strip())
else:
    raise SystemExit(1)
PY_STATE
}

# Explicit arguments take priority. Installed setups persist the app id and
# display name in the state file for subsequent BOOT starts.
if [ -z "$APP_ID" ]; then
  APP_ID="$(state_value app_id || true)"
fi
if [ "$APP_NAME_SET" = "0" ]; then
  state_name="$(state_value app_name || true)"
  if [ -n "$state_name" ]; then
    APP_NAME="$state_name"
  fi
fi
if [ -z "$APP_ID" ]; then
  json_emit blocked app_id_missing "run setup_liveware.py before starting the dashboard"
  exit 2
fi

resolve_liveware() {
  if [ -n "$LIVEWARE_ARG" ]; then
    [ -x "$LIVEWARE_ARG" ] || return 1
    printf '%s\n' "$LIVEWARE_ARG"
    return 0
  fi
  if command -v liveware >/dev/null 2>&1; then
    command -v liveware
    return 0
  fi
  if [ -x "$HERMES_HOME/clawchat/liveware/liveware" ]; then
    printf '%s\n' "$HERMES_HOME/clawchat/liveware/liveware"
    return 0
  fi
  return 1
}

if ! LIVEWARE_PATH="$(resolve_liveware)"; then
  json_emit blocked liveware_missing "run setup_liveware.py before starting the dashboard" "$APP_ID"
  exit 2
fi
export PATH="$(dirname "$LIVEWARE_PATH"):$PATH"

run_with_timeout() {
  if command -v timeout >/dev/null 2>&1; then
    timeout "$TIMEOUT_SECONDS" "$@"
  else
    "$@"
  fi
}

health_ok() {
  python3 - "$HOST" "$PORT" "$BOOK" <<'PY_HEALTH'
import json, os, sys, urllib.request
host, port, expected_book = sys.argv[1:4]
try:
    with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=1.5) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    actual = os.path.abspath(os.path.expanduser(str(payload.get("book") or "")))
    expected = os.path.abspath(os.path.expanduser(expected_book))
    raise SystemExit(0 if payload.get("ok") is True and actual == expected else 1)
except Exception:
    raise SystemExit(1)
PY_HEALTH
}

stop_old_service() {
  local pid_file="$DATA_DIR/liveware-dashboard.pid" old_pid=""
  if [ -f "$pid_file" ]; then
    old_pid="$(cat "$pid_file" 2>/dev/null || true)"
  fi
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    old_command="$(ps -p "$old_pid" -o command= 2>/dev/null || true)"
    if [[ "$old_command" == *"liveware/serve.py"* ]]; then
      kill "$old_pid" 2>/dev/null || true
      for _ in $(seq 1 20); do
        kill -0 "$old_pid" 2>/dev/null || break
        sleep 0.1
      done
    fi
  fi
  rm -f "$pid_file"
}

start_service() {
  local logs="$DATA_DIR/logs" pid_file="$DATA_DIR/liveware-dashboard.pid"
  mkdir -p "$logs"
  nohup python3 "$SKILL_DIR/liveware/serve.py" --host "$HOST" --port "$PORT" --book "$BOOK" \
    >>"$logs/liveware-dashboard.out.log" \
    2>>"$logs/liveware-dashboard.err.log" </dev/null &
  echo "$!" > "$pid_file"
  for _ in $(seq 1 30); do
    if health_ok; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

extract_url() {
  local text="$1"
  python3 - "$text" "$APP_ID" <<'PY_URL'
import json, re, sys
from urllib.parse import urlparse
text, app_id = sys.argv[1:3]

def is_public(value):
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return False
    host = (urlparse(value).hostname or "").lower()
    return host not in {"127.0.0.1", "localhost", "::1"}

try:
    payload = json.loads(text)
except Exception:
    payload = None
for source in (payload, payload.get("data") if isinstance(payload, dict) else None):
    if not isinstance(source, dict):
        continue
    for key in ("public_url", "publicUrl", "tunnel_url", "tunnelUrl", "url"):
        value = source.get(key)
        if is_public(value):
            print(value.strip())
            raise SystemExit(0)
domain_match = re.search(r"\b([A-Za-z0-9.-]+\.apps\.clawling\.io)\b", text)
if domain_match:
    print("https://" + domain_match.group(1))
    raise SystemExit(0)
for value in re.findall(r"https?://[^\s\"'<>]+", text):
    value = value.rstrip(".,)")
    if is_public(value):
        print(value)
        raise SystemExit(0)
print(f"https://{app_id}.apps.clawling.io")
PY_URL
}

save_state() {
  local public_url="$1" local_url="http://$HOST:$PORT"
  python3 - "$STATE_FILE" "$APP_NAME" "$APP_ID" "$public_url" "$local_url" "$BOOK" <<'PY_SAVE'
from pathlib import Path
import json, os, sys, time
path, app_name, app_id, public_url, local_url, book = sys.argv[1:7]
state_path = Path(path)
state = {}
if state_path.exists():
    try:
        loaded = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            state.update(loaded)
    except Exception:
        pass
state.update({
    "app_name": app_name,
    "app_id": app_id,
    "public_url": public_url,
    "local_url": local_url,
    "book": book,
    "started": True,
    "updated_at": int(time.time()),
})
state_path.parent.mkdir(parents=True, exist_ok=True)
temporary = state_path.with_name(state_path.name + ".tmp")
temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, state_path)
PY_SAVE
}

agent_alive() {
  local pid_file="$DATA_DIR/liveware-agent.pid" pid=""
  [ -f "$pid_file" ] || return 1
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$command_line" == *"liveware"*" agent"* ]]
}

start_agent() {
  local logs="$DATA_DIR/logs" pid_file="$DATA_DIR/liveware-agent.pid" old_pid=""
  mkdir -p "$logs"
  if agent_alive; then
    return 0
  fi
  if [ -f "$pid_file" ]; then
    old_pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
      kill "$old_pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
  fi
  nohup env HOME="$HERMES_HOME" "$LIVEWARE_PATH" agent \
    >>"$logs/liveware-agent.out.log" \
    2>>"$logs/liveware-agent.err.log" </dev/null &
  echo "$!" > "$pid_file"
}

stop_old_service
start_service || { json_emit blocked service_unhealthy "local account service did not become healthy" "$APP_ID"; exit 2; }

bind_output="$(HOME="$HERMES_HOME" run_with_timeout "$LIVEWARE_PATH" tunnel bind "$APP_ID" "http://$HOST:$PORT" 2>&1)" || {
  json_emit blocked liveware_tunnel_bind_failed "$bind_output" "$APP_ID"
  exit 2
}
PUBLIC_URL="$(extract_url "$bind_output")"
start_agent
save_state "$PUBLIC_URL"
json_emit ok "" "" "$APP_ID" "$PUBLIC_URL"
