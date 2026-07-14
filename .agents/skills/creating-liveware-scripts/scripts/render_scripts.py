#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import shlex
import tempfile
from pathlib import Path
from typing import cast

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSET_ROOT = SKILL_ROOT / "assets"
ANALYSIS_MARKER_PREFIX = "# LIVEWARE ANALYSIS V1: "
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PLACEHOLDER_TOKEN_RE = re.compile(r"@@[^\r\n]*?@@")
TOP_LEVEL_REQUIRED = frozenset(
    {
        "schema_version",
        "status",
        "target_root",
        "skill_name",
        "adapter",
        "static_dir",
        "evidence",
        "issues",
    }
)
TOP_LEVEL_OPTIONAL = frozenset({"display_name"})
ADAPTER_PROPERTIES = frozenset(
    {
        "kind",
        "workdir",
        "command",
        "required_commands",
        "default_port",
        "readiness",
        "log",
    }
)
READINESS_PROPERTIES = frozenset({"kind", "url"})
LOG_PROPERTIES = frozenset({"owner", "path"})
EVIDENCE_PROPERTIES = frozenset({"path", "reason"})
PORT_ENV_EVIDENCE_REASON = "Command consumes exported PORT environment variable"


def require_exact_properties(
    value: object,
    required: frozenset[str],
    label: str,
    optional: frozenset[str] = frozenset(),
) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object with the exact analyzer schema.")
    keys = set(value)
    if not required <= keys:
        raise ValueError(f"{label} is missing a required analyzer schema property.")
    if not keys <= required | optional:
        raise ValueError(f"{label} contains an additional analyzer schema property.")
    return value


def require_ready(analysis: dict[str, object]) -> None:
    if type(analysis) is dict and "target_root" not in analysis:
        raise ValueError(
            "Analysis target_root must be a non-empty string; this required schema property is missing."
        )
    analysis = require_exact_properties(
        analysis,
        TOP_LEVEL_REQUIRED,
        "Analysis",
        TOP_LEVEL_OPTIONAL,
    )
    schema_version = analysis["schema_version"]
    if type(schema_version) is not int or schema_version != 1 or analysis["status"] != "ready":
        raise ValueError("Analysis must use schema version 1 and have status ready.")
    if type(analysis["issues"]) is not list or analysis["issues"] != []:
        raise ValueError("Analysis contains unresolved issues.")
    target_root = analysis["target_root"]
    if not isinstance(target_root, str) or not target_root:
        raise ValueError("Analysis target_root must be a non-empty string.")
    if any(ord(character) < 32 or ord(character) == 127 for character in target_root):
        raise ValueError("Analysis target_root must not contain a control character.")
    target_path = Path(target_root)
    if (
        not target_path.is_absolute()
        or ".." in target_path.parts
        or target_root.startswith("//")
        or os.path.normpath(target_root) != target_root
    ):
        raise ValueError("Analysis target_root must be an absolute normalized path.")
    skill_name = analysis["skill_name"]
    if isinstance(skill_name, str) and any(
        ord(character) < 32 or ord(character) == 127 for character in skill_name
    ):
        raise ValueError("skill_name must not contain a control character.")
    if not isinstance(skill_name, str) or SKILL_NAME_RE.fullmatch(skill_name) is None:
        raise ValueError("Analysis skill_name must be a valid skill identifier.")
    display_name = analysis.get("display_name")
    if "display_name" in analysis and not isinstance(display_name, str):
        raise ValueError("Analysis display_name must be a string when present.")
    evidence = analysis["evidence"]
    if type(evidence) is not list:
        raise ValueError("Analysis evidence must be a list of analyzer schema objects.")
    for item in evidence:
        item = require_exact_properties(item, EVIDENCE_PROPERTIES, "Analysis evidence item")
        if not isinstance(item["path"], str) or not isinstance(item["reason"], str):
            raise ValueError("Analysis evidence path and reason must be strings.")
        require_resolved_target_path(analysis, item["path"], "Analysis evidence path")
    validate_adapter(analysis)


def _canonical_analysis_bytes(analysis: dict[str, object]) -> bytes:
    require_ready(analysis)
    return json.dumps(
        analysis,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def encode_analysis_manifest(analysis: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(_canonical_analysis_bytes(analysis)).decode("ascii")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Analysis manifest JSON contains duplicate keys.")
        result[key] = value
    return result


def _reject_non_json_number(value: str) -> object:
    raise ValueError(f"Analysis manifest contains non-JSON number {value}.")


def decode_analysis_manifest(payload: str) -> dict[str, object]:
    if not isinstance(payload, str) or not payload:
        raise ValueError("Analysis manifest payload must be non-empty URL-safe Base64.")
    try:
        encoded = payload.encode("ascii")
        raw = base64.b64decode(encoded, altchars=b"-_", validate=True)
        text = raw.decode("utf-8")
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_json_number,
        )
    except (UnicodeEncodeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise ValueError("Analysis manifest payload is malformed.") from exc
    if not isinstance(decoded, dict):
        raise ValueError("Analysis manifest JSON must be an object.")
    require_ready(decoded)
    if encode_analysis_manifest(decoded) != payload:
        raise ValueError("Analysis manifest payload is not canonical.")
    return decoded


def extract_analysis_manifest_payload(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("Script must be text.")
    payloads: list[str] = []
    for line in text.splitlines():
        if line.startswith(ANALYSIS_MARKER_PREFIX):
            payloads.append(line[len(ANALYSIS_MARKER_PREFIX):])
    if len(payloads) != 1:
        raise ValueError("Script must contain exactly one Liveware analysis manifest marker.")
    decode_analysis_manifest(payloads[0])
    return payloads[0]


def extract_analysis_manifest(text: str) -> dict[str, object]:
    return decode_analysis_manifest(extract_analysis_manifest_payload(text))


def analysis_manifest_line(analysis: dict[str, object]) -> str:
    return ANALYSIS_MARKER_PREFIX + encode_analysis_manifest(analysis)


def render_template(
    template: str,
    replacements: dict[str, str],
    label: str,
) -> str:
    if not isinstance(template, str) or not isinstance(replacements, dict):
        raise ValueError(f"{label} template and replacements must be text mappings.")
    if not replacements or any(
        not isinstance(marker, str)
        or PLACEHOLDER_TOKEN_RE.fullmatch(marker) is None
        or not isinstance(value, str)
        for marker, value in replacements.items()
    ):
        raise ValueError(f"{label} template placeholders are malformed.")

    matches = list(PLACEHOLDER_TOKEN_RE.finditer(template))
    tokens = [match.group(0) for match in matches]
    unknown = set(tokens) - set(replacements)
    if unknown:
        raise ValueError(f"{label} template contains an unknown placeholder.")
    if any(tokens.count(marker) != 1 for marker in replacements):
        raise ValueError(f"{label} template must contain every expected placeholder exactly once.")

    offset = 0
    for match in matches:
        if "@@" in template[offset:match.start()]:
            raise ValueError(f"{label} template contains a malformed placeholder.")
        offset = match.end()
    if "@@" in template[offset:]:
        raise ValueError(f"{label} template contains a malformed placeholder.")

    return PLACEHOLDER_TOKEN_RE.sub(
        lambda match: replacements[match.group(0)],
        template,
    )


def render_setup(analysis: dict[str, object]) -> str:
    require_ready(analysis)
    template = (ASSET_ROOT / "setup.py.tmpl").read_text(encoding="utf-8")
    replacements = {
        "@@ANALYSIS_MANIFEST@@": analysis_manifest_line(analysis),
        "@@SKILL_NAME@@": json.dumps(analysis["skill_name"], ensure_ascii=False),
        "@@DISPLAY_NAME@@": json.dumps(analysis.get("display_name") or analysis["skill_name"], ensure_ascii=False),
    }
    return render_template(template, replacements, "Setup")


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
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_non_json_number,
    )
    if not isinstance(payload, dict):
        raise ValueError("Analysis JSON must be an object.")
    require_ready(payload)
    return payload


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_target_root(analysis: dict[str, object], requested: Path) -> Path:
    require_ready(analysis)
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
REQUIRED_COMMAND_RE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._+@-]*$")


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


def require_resolved_target_path(
    analysis: dict[str, object],
    value: object,
    label: str,
) -> str:
    text = require_target_relative_path(value, label)
    target_root = analysis.get("target_root")
    if not isinstance(target_root, str):
        raise ValueError("Analysis target_root must be a non-empty string.")
    try:
        resolved_root = Path(target_root).resolve(strict=False)
        resolved_path = (Path(target_root) / text).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"{label} could not be resolved safely.") from exc
    if not path_is_within(resolved_path, resolved_root):
        raise ValueError(f"{label} would escape outside the target root.")
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


def require_generated_log_path(value: object) -> str:
    text = require_shell_text(value, "Generated-start log path")
    for prefix in ("${HOME}/", "$HOME/"):
        if text.startswith(prefix):
            suffix = text[len(prefix):]
            path = Path(suffix)
            if (
                not suffix
                or suffix == "."
                or path.is_absolute()
                or ".." in path.parts
                or os.path.normpath(suffix) != suffix
            ):
                raise ValueError(
                    "Generated-start log path must be normalized under $HOME without traversal."
                )
            return text
    path = Path(text)
    if (
        not path.is_absolute()
        or text == "/"
        or text.startswith("//")
        or ".." in path.parts
        or os.path.normpath(text) != text
    ):
        raise ValueError(
            "Generated-start log path must be a normalized absolute path or use $HOME/."
        )
    return text


def validate_adapter(analysis: dict[str, object]) -> dict[str, object]:
    adapter = require_exact_properties(
        analysis.get("adapter"),
        ADAPTER_PROPERTIES,
        "Analysis adapter",
    )
    kind = adapter["kind"]
    if kind not in {"managed-command", "existing-launcher", "external", "static"}:
        raise ValueError("Analysis adapter kind is not renderable.")
    workdir = require_resolved_target_path(analysis, adapter["workdir"], "Adapter workdir")
    command = adapter["command"]
    if type(command) is not list or not all(isinstance(item, str) for item in command):
        raise ValueError("Adapter command must be an argv list.")
    port_placeholders = 0
    for item in command:
        require_shell_text(item, "Adapter command argument", allow_empty=True)
        if "{port}" in item:
            if item != "{port}":
                raise ValueError("The command port placeholder must be a standalone {port} argv item.")
            port_placeholders += 1
    if port_placeholders > 1:
        raise ValueError("The command may contain at most one standalone {port} placeholder.")
    required = adapter["required_commands"]
    if type(required) is not list or not all(isinstance(item, str) for item in required):
        raise ValueError("required_commands must be a string list.")
    for item in required:
        name = require_shell_text(item, "Required command")
        if REQUIRED_COMMAND_RE.fullmatch(name) is None:
            raise ValueError("Required command name is malformed or option-like.")
    log = require_exact_properties(adapter["log"], LOG_PROPERTIES, "Adapter log declaration")
    owner = log["owner"]
    log_path = log["path"]
    if owner not in {"target", "generated-start"}:
        raise ValueError("Adapter log owner must be target or generated-start.")
    if log_path is not None:
        require_shell_text(log_path, "Adapter log path")

    if kind == "static":
        if command or required or adapter["default_port"] is not None or adapter["readiness"] is not None:
            raise ValueError("Static adapters must not define commands, a port, or readiness.")
        if owner != "target" or log_path is not None:
            raise ValueError("Static adapters must retain target log ownership.")
        static_dir = require_resolved_target_path(analysis, analysis["static_dir"], "Static directory")
        if workdir != static_dir:
            raise ValueError("Static adapter workdir must equal static_dir.")
        return adapter

    static_dir = analysis["static_dir"]
    if static_dir is not None:
        require_resolved_target_path(analysis, static_dir, "Dynamic static directory")
    port = adapter["default_port"]
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Dynamic adapter requires a valid default port.")
    if kind != "external" and not command:
        raise ValueError("Managed and existing-launcher adapters require a command.")
    if kind == "external" and command:
        raise ValueError("External adapters must not define a start command.")
    if kind in {"managed-command", "existing-launcher"} and port_placeholders == 0:
        evidence = analysis.get("evidence")
        if type(evidence) is not list or not any(
            type(item) is dict and item.get("reason") == PORT_ENV_EVIDENCE_REASON
            for item in evidence
        ):
            raise ValueError(
                "A dynamic command without {port} requires exact exported PORT evidence."
            )
    readiness = require_exact_properties(
        adapter["readiness"],
        READINESS_PROPERTIES,
        "Adapter readiness declaration",
    )
    if readiness["kind"] != "http":
        raise ValueError("Dynamic adapter requires an HTTP readiness check.")
    url = require_shell_text(readiness["url"], "Dynamic readiness URL")
    prefix = "http://127.0.0.1:{port}"
    if not url.startswith(prefix + "/") or url.count("{port}") != 1:
        raise ValueError("Dynamic readiness URL must use the exact loopback {port} structure.")
    if kind in {"existing-launcher", "external"} and (owner != "target" or log_path is not None):
        raise ValueError(f"{kind} adapters must retain target log ownership.")
    if kind == "managed-command" and owner == "generated-start":
        if not isinstance(log_path, str):
            raise ValueError("Generated-start logging requires an explicit log file.")
        require_generated_log_path(log_path)
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
        f"if ! command -v -- {shlex.quote(item)} >/dev/null 2>&1; then printf 'start: Missing required command: %s.\\n' {shlex.quote(item)} >&2; exit 1; fi"
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
    launch = f'''\ncd -- {shell_root_path(workdir)}
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
mkdir -p -- "$(dirname -- "$SERVER_LOG")"'''
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


def _render_fresh_start(analysis: dict[str, object]) -> str:
    skill_name = require_shell_text(analysis.get("skill_name"), "skill_name")
    adapter = validate_adapter(analysis)
    generated_adapter = "# Static content requires no server process."
    if adapter["kind"] in {"managed-command", "existing-launcher", "external"}:
        generated_adapter = _render_dynamic_adapter(adapter)
    binding = render_binding(analysis)
    template = (ASSET_ROOT / "start.sh.tmpl").read_text(encoding="utf-8")
    replacements = {
        "@@ANALYSIS_MANIFEST@@": analysis_manifest_line(analysis),
        "@@SKILL_NAME@@": shlex.quote(skill_name),
        "@@TARGET_SERVER_ADAPTER@@": generated_adapter,
        "@@LIVEWARE_BINDING@@": binding,
    }
    return render_template(template, replacements, "Start")


def render_start(analysis: dict[str, object], existing: str | None = None) -> str:
    require_ready(analysis)
    fresh = _render_fresh_start(analysis)
    if existing is None:
        return fresh

    embedded_payload = extract_analysis_manifest_payload(existing)
    if embedded_payload != encode_analysis_manifest(analysis):
        raise ValueError("Existing start.sh analysis manifest does not match current analysis.")
    existing_spans = parse_marker_spans(existing)
    fresh_spans = parse_marker_spans(fresh)
    existing_prefix = existing[:existing_spans[BEGIN_BINDING][1]]
    existing_suffix = existing[existing_spans[END_BINDING][0]:]
    fresh_prefix = fresh[:fresh_spans[BEGIN_BINDING][1]]
    fresh_suffix = fresh[fresh_spans[END_BINDING][0]:]
    if existing_prefix != fresh_prefix or existing_suffix != fresh_suffix:
        raise ValueError("Existing start.sh differs from the canonical scaffold outside binding content.")
    fresh_binding = fresh[fresh_spans[BEGIN_BINDING][1]:fresh_spans[END_BINDING][0]]
    return existing_prefix + fresh_binding + existing_suffix


def validate_existing_manifest_pair(setup: str, start: str, analysis: dict[str, object]) -> None:
    try:
        setup_payload = extract_analysis_manifest_payload(setup)
        start_payload = extract_analysis_manifest_payload(start)
        current_payload = encode_analysis_manifest(analysis)
    except ValueError as exc:
        raise ValueError("Existing setup/start manifest pair is missing or invalid.") from exc
    if setup_payload != start_payload or setup_payload != current_payload:
        raise ValueError("Existing setup/start manifest pair does not match current analysis.")


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
    if existing is not None:
        if not setup_path.is_file():
            raise ValueError("Existing setup/start manifest pair is incomplete.")
        validate_existing_manifest_pair(
            setup_path.read_text(encoding="utf-8"),
            existing,
            analysis,
        )
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
