#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSET_ROOT = SKILL_ROOT / "assets"


def require_ready(analysis: dict[str, object]) -> None:
    if analysis.get("schema_version") != 1 or analysis.get("status") != "ready":
        raise ValueError("Analysis must use schema version 1 and have status ready.")
    if analysis.get("issues"):
        raise ValueError("Analysis contains unresolved issues.")


def render_setup(analysis: dict[str, object]) -> str:
    require_ready(analysis)
    template = (ASSET_ROOT / "setup.py.tmpl").read_text(encoding="utf-8")
    replacements = {
        "@@SKILL_NAME@@": json.dumps(analysis["skill_name"], ensure_ascii=False),
        "@@DISPLAY_NAME@@": json.dumps(analysis.get("display_name") or analysis["skill_name"], ensure_ascii=False),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    if "@@" in template:
        raise ValueError("Setup template contains unresolved markers.")
    return template


def atomic_write(path: Path, text: str, mode: int = 0o755) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_analysis(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Analysis JSON must be an object.")
    return payload


BEGIN_ADAPTER = "# BEGIN TARGET SERVER ADAPTER"
END_ADAPTER = "# END TARGET SERVER ADAPTER"
BEGIN_BINDING = "# BEGIN LIVEWARE BINDING"
END_BINDING = "# END LIVEWARE BINDING"


def shell_word(value: str) -> str:
    return '"${PORT}"' if value == "{port}" else shlex.quote(value)


def extract_block(text: str, begin: str, end: str) -> str:
    pattern = re.compile(rf"(?ms)^{re.escape(begin)}\n(.*?)^{re.escape(end)}$")
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"Existing start.sh is missing marker {begin}.")
    return match.group(1).rstrip("\n")


def render_dynamic_adapter(analysis: dict[str, object]) -> str:
    adapter = analysis["adapter"]
    assert isinstance(adapter, dict)
    kind = adapter.get("kind")
    port = adapter.get("default_port")
    command = adapter.get("command")
    readiness = adapter.get("readiness")
    required = adapter.get("required_commands")
    workdir = adapter.get("workdir")
    if kind not in {"managed-command", "existing-launcher", "external"}:
        raise ValueError("Unsupported dynamic adapter kind.")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Dynamic adapter requires a valid default port.")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError("Dynamic adapter command must be an argv list.")
    if kind != "external" and not command:
        raise ValueError("Managed and existing-launcher adapters require a command.")
    if kind == "external" and command:
        raise ValueError("External adapters must not define a start command.")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError("required_commands must be a string list.")
    if not isinstance(readiness, dict) or readiness.get("kind") != "http":
        raise ValueError("Dynamic adapter requires an HTTP readiness check.")
    url = readiness.get("url")
    if not isinstance(url, str) or not url.startswith("http://127.0.0.1:{port}/"):
        raise ValueError("Dynamic readiness URL must use loopback.")
    if not isinstance(workdir, str) or workdir.startswith("/") or ".." in Path(workdir).parts:
        raise ValueError("Adapter workdir must be target-relative.")
    health = url.replace("{port}", "${PORT}")
    command_checks = "\n".join(
        f'if ! command -v {shlex.quote(item)} >/dev/null 2>&1; then echo "start: Missing required command: {item}." >&2; exit 1; fi'
        for item in required
    )
    common = f'''PORT="${{PORT:-{port}}}"
case "$PORT" in ''|*[!0-9]*) echo "start: PORT must be an integer from 1 to 65535." >&2; exit 1;; esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then echo "start: PORT must be an integer from 1 to 65535." >&2; exit 1; fi
export PORT
{command_checks}
wait_for_http() {{
  python3 - "$1" <<'PY'
import sys
import time
import urllib.request
url = sys.argv[1]
for _ in range(40):
    try:
        with urllib.request.urlopen(url, timeout=0.5):
            raise SystemExit(0)
    except Exception:
        time.sleep(0.25)
raise SystemExit(1)
PY
}}'''
    if kind == "external":
        return common + f'''\nprintf 'Target service is externally managed; checking %s.\n' "{health}"
if ! wait_for_http "{health}"; then
  echo "start: Externally managed target service is not ready." >&2
  exit 1
fi'''
    words = " ".join(shell_word(item) for item in command)
    launch = f'''\ncd "$SKILL_ROOT/{workdir}"
SERVER_COMMAND=({words})'''
    if kind == "existing-launcher":
        return common + launch + f'''\n"${{SERVER_COMMAND[@]}}"
if ! wait_for_http "{health}"; then
  echo "start: Existing launcher returned but the target service is not ready." >&2
  exit 1
fi'''
    log = adapter.get("log")
    if not isinstance(log, dict) or log.get("owner") not in {"target", "generated-start"}:
        raise ValueError("Managed command must declare target or generated-start log ownership.")
    if log.get("owner") == "generated-start":
        log_path = log.get("path")
        if not isinstance(log_path, str) or not log_path:
            raise ValueError("Generated-start logging requires an explicit log file.")
        log_setup = f'''SERVER_LOG="{log_path}"
mkdir -p "$(dirname "$SERVER_LOG")"'''
        launch_command = '"${SERVER_COMMAND[@]}" >"$SERVER_LOG" 2>&1 &'
        ready_error = 'echo "start: Target server did not become ready. Log: $SERVER_LOG" >&2'
    else:
        log_setup = "# The target server owns its existing logging strategy."
        launch_command = '"${SERVER_COMMAND[@]}" &'
        ready_error = 'echo "start: Target server did not become ready." >&2'
    return common + f'''\nport_is_free() {{
  python3 - "$1" <<'PY'
import socket
import sys
with socket.socket() as probe:
    probe.bind(("127.0.0.1", int(sys.argv[1])))
PY
}}
if ! port_is_free "$PORT"; then
  echo "start: PORT is already occupied; refusing to replace an unknown process." >&2
  exit 1
fi
{log_setup}''' + launch + f'''\n{launch_command}
SERVER_PID=$!
printf 'Started target server with PID %s.\n' "$SERVER_PID"
if ! wait_for_http "{health}"; then
  {ready_error}
  exit 1
fi'''


def render_binding(analysis: dict[str, object]) -> str:
    adapter = analysis["adapter"]
    assert isinstance(adapter, dict)
    if adapter.get("kind") == "static":
        static_dir = analysis.get("static_dir")
        if not isinstance(static_dir, str) or static_dir.startswith("/") or ".." in Path(static_dir).parts:
            raise ValueError("Static directory must be target-relative.")
        return f'"$LIVEWARE_BIN" tunnel bind-static "$APP_ID" "$SKILL_ROOT/{static_dir}"'
    if adapter.get("kind") in {"managed-command", "existing-launcher", "external"}:
        return '"$LIVEWARE_BIN" tunnel bind "$APP_ID" "http://127.0.0.1:${PORT}"'
    raise ValueError("User-confirmed adapter kind is not renderable.")


def render_start(analysis: dict[str, object], existing: str | None = None) -> str:
    require_ready(analysis)
    adapter = analysis["adapter"]
    assert isinstance(adapter, dict)
    generated_adapter = "# Static content requires no server process."
    if adapter.get("kind") in {"managed-command", "existing-launcher", "external"}:
        generated_adapter = render_dynamic_adapter(analysis)
    if existing is not None:
        generated_adapter = extract_block(existing, BEGIN_ADAPTER, END_ADAPTER)
    template = (ASSET_ROOT / "start.sh.tmpl").read_text(encoding="utf-8")
    replacements = {
        "@@SKILL_NAME@@": shlex.quote(str(analysis["skill_name"])),
        "@@TARGET_SERVER_ADAPTER@@": generated_adapter,
        "@@LIVEWARE_BINDING@@": render_binding(analysis),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    if "@@" in template:
        raise ValueError("Start template contains unresolved markers.")
    return template


def main() -> int:
    parser = argparse.ArgumentParser(description="Render standard Liveware scripts from approved target analysis.")
    parser.add_argument("target", type=Path)
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    analysis = load_analysis(args.analysis)
    target = args.target.expanduser().resolve()
    if Path(str(analysis.get("target_root", ""))).expanduser().resolve() != target:
        raise ValueError("Analysis target_root does not match the requested target.")
    setup_text = render_setup(analysis)
    start_path = target / "liveware" / "scripts" / "start.sh"
    existing = start_path.read_text(encoding="utf-8") if start_path.is_file() else None
    if existing is not None and not all(marker in existing for marker in (BEGIN_ADAPTER, END_ADAPTER, BEGIN_BINDING, END_BINDING)):
        raise ValueError("Existing start.sh has no safe adapter markers; inspect it and resolve the server adapter before repair.")
    start_text = render_start(analysis, existing=existing)
    if not args.apply:
        print(json.dumps({"setup.py": setup_text, "start.sh": start_text}, ensure_ascii=False, indent=2))
        return 0
    atomic_write(target / "liveware" / "scripts" / "setup.py", setup_text)
    atomic_write(start_path, start_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
