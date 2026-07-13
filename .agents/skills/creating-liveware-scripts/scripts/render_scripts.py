#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import tempfile
from pathlib import Path
from typing import cast

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSET_ROOT = SKILL_ROOT / "assets"


def require_ready(analysis: dict[str, object]) -> None:
    if not isinstance(analysis, dict):
        raise ValueError("Analysis must be an object.")
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


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_target_root(analysis: dict[str, object], requested: Path) -> Path:
    raw_target = require_shell_text(analysis.get("target_root"), "Analysis target_root")
    target = requested.expanduser().resolve()
    try:
        analyzed = Path(raw_target).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("Analysis target_root could not be resolved.") from exc
    if analyzed != target:
        raise ValueError("Analysis target_root does not match the requested target.")
    return target


def validate_script_paths(target: Path) -> tuple[Path, Path]:
    liveware = target / "liveware"
    scripts = liveware / "scripts"
    for parent in (liveware, scripts):
        if parent.is_symlink():
            raise ValueError(f"Refusing symlinked script parent: {parent}")
        if not path_is_within(parent.resolve(strict=False), target):
            raise ValueError(f"Script parent would escape the target root: {parent}")
    setup_path = scripts / "setup.py"
    start_path = scripts / "start.sh"
    for output in (setup_path, start_path):
        if not path_is_within(output.resolve(strict=False), target):
            raise ValueError(f"Script path would escape the target root: {output}")
    return setup_path, start_path


BEGIN_ADAPTER = "# BEGIN TARGET SERVER ADAPTER"
END_ADAPTER = "# END TARGET SERVER ADAPTER"
BEGIN_BINDING = "# BEGIN LIVEWARE BINDING"
END_BINDING = "# END LIVEWARE BINDING"
MARKERS = (BEGIN_ADAPTER, END_ADAPTER, BEGIN_BINDING, END_BINDING)


def require_shell_text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"{label} must be a{' non-empty' if not allow_empty else ''} string.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{label} must not contain a control character.")
    return value


def require_target_relative_path(value: object, label: str) -> str:
    text = require_shell_text(value, label)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be target-relative.")
    return text


def shell_double_data(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


def shell_root_path(value: str) -> str:
    return f'"$SKILL_ROOT/{shell_double_data(value)}"'


def shell_health_url(value: str) -> str:
    prefix = "http://127.0.0.1:{port}"
    suffix = value[len(prefix):]
    return f'"http://127.0.0.1:${{PORT}}{shell_double_data(suffix)}"'


def shell_log_path(value: str) -> str:
    for prefix in ("${HOME}/", "$HOME/"):
        if value.startswith(prefix):
            suffix = require_target_relative_path(value[len(prefix):], "Generated-start log path")
            return f'"${{HOME}}/{shell_double_data(suffix)}"'
    return shlex.quote(value)


def validate_adapter(analysis: dict[str, object]) -> dict[str, object]:
    adapter = analysis.get("adapter")
    if not isinstance(adapter, dict):
        raise ValueError("Analysis adapter must be an object mapping.")
    kind = adapter.get("kind")
    if kind not in {"managed-command", "existing-launcher", "external", "static"}:
        raise ValueError("Analysis adapter kind is not renderable.")
    workdir = require_target_relative_path(adapter.get("workdir"), "Adapter workdir")
    command = adapter.get("command")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError("Adapter command must be an argv list.")
    for item in command:
        require_shell_text(item, "Adapter command argument", allow_empty=True)
    required = adapter.get("required_commands")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError("required_commands must be a string list.")
    for item in required:
        require_shell_text(item, "Required command")
    log = adapter.get("log")
    if not isinstance(log, dict):
        raise ValueError("Adapter log declaration must be an object mapping.")
    owner = log.get("owner")
    log_path = log.get("path")
    if owner not in {"target", "generated-start"}:
        raise ValueError("Adapter log owner must be target or generated-start.")
    if log_path is not None:
        require_shell_text(log_path, "Adapter log path")

    if kind == "static":
        if command or required or adapter.get("default_port") is not None or adapter.get("readiness") is not None:
            raise ValueError("Static adapters must not define commands, a port, or readiness.")
        if owner != "target" or log_path is not None:
            raise ValueError("Static adapters must retain target log ownership.")
        require_target_relative_path(analysis.get("static_dir"), "Static directory")
        return adapter

    port = adapter.get("default_port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Dynamic adapter requires a valid default port.")
    if kind != "external" and not command:
        raise ValueError("Managed and existing-launcher adapters require a command.")
    if kind == "external" and command:
        raise ValueError("External adapters must not define a start command.")
    readiness = adapter.get("readiness")
    if not isinstance(readiness, dict) or readiness.get("kind") != "http":
        raise ValueError("Dynamic adapter requires an HTTP readiness check.")
    url = require_shell_text(readiness.get("url"), "Dynamic readiness URL")
    prefix = "http://127.0.0.1:{port}"
    if not url.startswith(prefix + "/") or url.count("{port}") != 1:
        raise ValueError("Dynamic readiness URL must use the exact loopback {port} structure.")
    if kind in {"existing-launcher", "external"} and (owner != "target" or log_path is not None):
        raise ValueError(f"{kind} adapters must retain target log ownership.")
    if kind == "managed-command" and owner == "generated-start" and not isinstance(log_path, str):
        raise ValueError("Generated-start logging requires an explicit log file.")
    return adapter


def shell_word(value: str) -> str:
    return '"${PORT}"' if value == "{port}" else shlex.quote(value)


def parse_marker_spans(text: str) -> dict[str, tuple[int, int]]:
    if not isinstance(text, str):
        raise ValueError("Existing start.sh must be text.")
    found: dict[str, list[tuple[int, int]]] = {marker: [] for marker in MARKERS}
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.endswith("\r\n"):
            body = line[:-2]
        elif line.endswith(("\n", "\r")):
            body = line[:-1]
        else:
            body = line
        if body in found:
            found[body].append((offset, offset + len(line)))
        offset += len(line)
    if any(len(found[marker]) != 1 for marker in MARKERS):
        raise ValueError("Existing start.sh marker structure is invalid: each exact whole-line marker must appear once.")
    spans = {marker: found[marker][0] for marker in MARKERS}
    if not all(spans[left][0] < spans[right][0] for left, right in zip(MARKERS, MARKERS[1:])):
        raise ValueError("Existing start.sh marker structure is invalid: markers are reordered or nested.")
    return spans


def extract_block(text: str, begin: str, end: str) -> str:
    if begin not in MARKERS or end not in MARKERS:
        raise ValueError("Unknown start.sh marker requested.")
    spans = parse_marker_spans(text)
    return text[spans[begin][1]:spans[end][0]].rstrip("\n")


def _render_dynamic_adapter(adapter: dict[str, object]) -> str:
    kind = cast(str, adapter["kind"])
    port = cast(int, adapter["default_port"])
    command = cast(list[str], adapter["command"])
    readiness = cast(dict[str, object], adapter["readiness"])
    required = cast(list[str], adapter["required_commands"])
    workdir = cast(str, adapter["workdir"])
    log = cast(dict[str, object], adapter["log"])
    url = cast(str, readiness["url"])
    health = shell_health_url(url)
    command_checks = "\n".join(
        f"if ! command -v {shlex.quote(item)} >/dev/null 2>&1; then printf 'start: Missing required command: %s.\\n' {shlex.quote(item)} >&2; exit 1; fi"
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
        return common + f'''\nprintf 'Target service is externally managed; checking %s.\n' {health}
if ! wait_for_http {health}; then
  echo "start: Externally managed target service is not ready." >&2
  exit 1
fi'''
    words = " ".join(shell_word(item) for item in command)
    launch = f'''\ncd {shell_root_path(workdir)}
SERVER_COMMAND=({words})'''
    if kind == "existing-launcher":
        return common + launch + f'''\n"${{SERVER_COMMAND[@]}}"
if ! wait_for_http {health}; then
  echo "start: Existing launcher returned but the target service is not ready." >&2
  exit 1
fi'''
    if log["owner"] == "generated-start":
        log_path = cast(str, log["path"])
        log_setup = f'''SERVER_LOG={shell_log_path(log_path)}
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
if ! wait_for_http {health}; then
  {ready_error}
  exit 1
fi'''


def render_dynamic_adapter(analysis: dict[str, object]) -> str:
    adapter = validate_adapter(analysis)
    if adapter["kind"] not in {"managed-command", "existing-launcher", "external"}:
        raise ValueError("Unsupported dynamic adapter kind.")
    return _render_dynamic_adapter(adapter)


def render_binding(analysis: dict[str, object]) -> str:
    adapter = validate_adapter(analysis)
    if adapter["kind"] == "static":
        static_dir = require_target_relative_path(analysis.get("static_dir"), "Static directory")
        return f'"$LIVEWARE_BIN" tunnel bind-static "$APP_ID" {shell_root_path(static_dir)}'
    if adapter["kind"] in {"managed-command", "existing-launcher", "external"}:
        return '"$LIVEWARE_BIN" tunnel bind "$APP_ID" "http://127.0.0.1:${PORT}"'
    raise ValueError("User-confirmed adapter kind is not renderable.")


def render_start(analysis: dict[str, object], existing: str | None = None) -> str:
    require_ready(analysis)
    skill_name = require_shell_text(analysis.get("skill_name"), "skill_name")
    adapter = validate_adapter(analysis)
    generated_adapter = "# Static content requires no server process."
    if adapter["kind"] in {"managed-command", "existing-launcher", "external"}:
        generated_adapter = _render_dynamic_adapter(adapter)
    binding = render_binding(analysis)
    if existing is not None:
        spans = parse_marker_spans(existing)
        existing_adapter = existing[spans[BEGIN_ADAPTER][1]:spans[END_ADAPTER][0]]
        if existing_adapter != generated_adapter + "\n":
            raise ValueError("Existing start.sh target server adapter does not match current analysis.")
        binding_block = binding + "\nprintf 'Liveware ready: %s\\n' \"$PUBLIC_URL\"\n"
        return existing[:spans[BEGIN_BINDING][1]] + binding_block + existing[spans[END_BINDING][0]:]
    template = (ASSET_ROOT / "start.sh.tmpl").read_text(encoding="utf-8")
    replacements = {
        "@@SKILL_NAME@@": shlex.quote(skill_name),
        "@@TARGET_SERVER_ADAPTER@@": generated_adapter,
        "@@LIVEWARE_BINDING@@": binding,
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
    target = resolve_target_root(analysis, args.target)
    setup_path, start_path = validate_script_paths(target)
    setup_text = render_setup(analysis)
    existing = start_path.read_text(encoding="utf-8") if start_path.is_file() else None
    start_text = render_start(analysis, existing=existing)
    if not args.apply:
        print(json.dumps({"setup.py": setup_text, "start.sh": start_text}, ensure_ascii=False, indent=2))
        return 0
    setup_path, start_path = validate_script_paths(target)
    atomic_write(setup_path, setup_text)
    setup_path, start_path = validate_script_paths(target)
    atomic_write(start_path, start_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
