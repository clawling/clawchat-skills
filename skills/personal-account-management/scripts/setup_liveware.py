#!/usr/bin/env python3
"""First-use setup: create the dashboard app and register it with ClawChat once."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse
from pathlib import Path
from typing import Any


def emit(status: str, **values: Any) -> None:
    payload = {"status": status, **{key: value for key, value in values.items() if value not in (None, "")}}
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def resolve_liveware(args: argparse.Namespace, hermes_home: Path) -> Path:
    if args.liveware:
        candidate = Path(args.liveware).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
        raise RuntimeError(f"liveware is not executable: {candidate}")

    discovered = shutil.which("liveware")
    if discovered:
        return Path(discovered).resolve()

    liveware_dir = hermes_home / "clawchat" / "liveware"
    candidate = liveware_dir / "liveware"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate.resolve()
    raise RuntimeError("liveware is not installed; activate the ClawChat plugin before running setup")


def load_clawchat_tools(hermes_home: Path):
    try:
        from clawchat_gateway import tools  # type: ignore

        return tools
    except ImportError:
        pass

    script_plugin_dir = Path(__file__).resolve().parents[4] / "plugins" / "clawchat"
    candidates = [
        script_plugin_dir,
        hermes_home.parent / "plugins" / "clawchat",
        hermes_home / "plugins" / "clawchat",
    ]
    for candidate in candidates:
        if (candidate / "clawchat_gateway" / "tools.py").is_file():
            sys.path.insert(0, str(candidate))
            from clawchat_gateway import tools  # type: ignore

            return tools
    raise RuntimeError("ClawChat plugin tools are unavailable")


def run_liveware(liveware: Path, timeout: int, *arguments: str) -> str:
    completed = subprocess.run(
        [str(liveware), *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    output = completed.stdout or ""
    if completed.returncode != 0:
        raise RuntimeError(output.strip() or f"liveware exited with {completed.returncode}")
    return output


def app_records(output: str) -> list[dict[str, str]]:
    try:
        payload = json.loads(output)
    except Exception:
        payload = None

    values: Any = payload
    if isinstance(payload, dict):
        values = payload.get("apps") or payload.get("data") or payload.get("items") or []
        if isinstance(values, dict):
            values = values.get("apps") or values.get("items") or []
    records: list[dict[str, str]] = []
    if isinstance(values, list):
        for item in values:
            if not isinstance(item, dict):
                continue
            app_id = str(item.get("app_id") or item.get("appId") or item.get("id") or "").strip()
            if not app_id:
                continue
            records.append(
                {
                    "app_id": app_id,
                    "name": str(item.get("name") or "").strip(),
                    "domain": str(item.get("domain") or "").strip(),
                    "url": str(item.get("url") or item.get("public_url") or item.get("publicUrl") or "").strip(),
                }
            )
        if records:
            return records

    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.upper().startswith("APPID"):
            continue
        parts = line.split()
        if len(parts) < 6 or not parts[0].startswith("app-"):
            continue
        records.append(
            {
                "app_id": parts[0],
                "domain": parts[2],
                "name": " ".join(parts[3:-2]),
                "url": "",
            }
        )
    return records


def extract_created_app(output: str, app_name: str) -> dict[str, str]:
    records = app_records(output)
    if records:
        return records[0]

    app_id_match = re.search(r"\b(app-[A-Za-z0-9_.:-]+)\b", output)
    if not app_id_match:
        raise RuntimeError("liveware did not return an app id")
    url_match = re.search(r"https?://[^\s\"'<>]+", output)
    domain_match = re.search(r"\b([A-Za-z0-9.-]+\.apps\.clawling\.io)\b", output)
    return {
        "app_id": app_id_match.group(1),
        "name": app_name,
        "domain": domain_match.group(1) if domain_match else "",
        "url": url_match.group(0).rstrip(".,)") if url_match else "",
    }


def public_url(record: dict[str, str]) -> str:
    value = record.get("url", "").strip()
    if value.startswith(("http://", "https://")):
        host = (urlparse(value).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return value
    domain = record.get("domain", "").strip()
    if domain:
        return "https://" + domain
    app_id = record["app_id"]
    return f"https://{app_id}.apps.clawling.io"


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def contains_registered_app(payload: Any, app_id: str) -> bool:
    if isinstance(payload, dict):
        candidate = str(payload.get("app_id") or payload.get("appId") or payload.get("id") or "").strip()
        if candidate == app_id:
            return True
        return any(contains_registered_app(value, app_id) for value in payload.values())
    if isinstance(payload, list):
        return any(contains_registered_app(value, app_id) for value in payload)
    return False


def write_state(path: Path, *, app_name: str, app_id: str, url: str) -> None:
    state = read_state(path)
    state.update(
        {
            "app_name": app_name,
            "app_id": app_id,
            "public_url": url,
            "registered": True,
            "updated_at": int(time.time()),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


async def async_main(args: argparse.Namespace) -> int:
    hermes_home = Path(args.hermes_home).expanduser().resolve()
    state_file = Path(args.state_file).expanduser() if args.state_file else Path.home() / "personal-account-management" / "liveware-dashboard.state.json"
    saved_state = read_state(state_file)
    saved_app_id = str(saved_state.get("app_id") or "").strip()
    saved_url = str(saved_state.get("public_url") or "").strip()
    saved_name = str(saved_state.get("app_name") or args.app_name).strip()

    try:
        liveware = resolve_liveware(args, hermes_home)
        os.environ["HOME"] = str(hermes_home)
        os.environ["PATH"] = str(liveware.parent) + os.pathsep + os.environ.get("PATH", "")
        tools = load_clawchat_tools(hermes_home)

        login_result = await tools.liveware_login()
        if not isinstance(login_result, dict) or login_result.get("ok") is not True:
            emit("blocked", code="liveware_login_failed", message=str(login_result))
            return 2

        if saved_app_id:
            selected = {
                "app_id": saved_app_id,
                "name": saved_name,
                "url": saved_url,
                "domain": "",
            }
        else:
            list_output = run_liveware(liveware, args.timeout, "app", "list")
            records = app_records(list_output)
            selected = next((item for item in records if item.get("name") == args.app_name), None)
            if selected is None:
                create_output = run_liveware(liveware, args.timeout, "app", "create", args.app_name, "--agent-type", "hermes")
                selected = extract_created_app(create_output, args.app_name)

        app_id = selected["app_id"]
        url = public_url(selected)
        registered_apps = await tools.list_apps()
        already_registered = (
            isinstance(registered_apps, dict)
            and not registered_apps.get("error")
            and contains_registered_app(registered_apps, app_id)
        )
        if not already_registered:
            registration = await tools.register_app(name=args.app_name, app_id=app_id, url=url)
            if not isinstance(registration, dict) or registration.get("error"):
                emit("blocked", code="clawchat_registration_failed", message=str(registration), app_id=app_id)
                return 2

        write_state(state_file, app_name=args.app_name, app_id=app_id, url=url)
        emit(
            "ok",
            app_name=args.app_name,
            app_id=app_id,
            public_url=url,
            state_file=str(state_file),
            liveware=str(liveware),
            already_registered=already_registered,
        )
        return 0
    except subprocess.TimeoutExpired:
        emit("blocked", code="liveware_timeout", message="liveware command timed out")
        return 2
    except Exception as exc:  # noqa: BLE001
        emit("blocked", code="setup_failed", message=str(exc))
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and register the personal account dashboard app.")
    parser.add_argument("--app-name", default=os.environ.get("HERMES_ACCOUNT_LIVEWARE_APP_NAME", "Account Book"))
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--state-file")
    parser.add_argument("--liveware")
    parser.add_argument("--timeout", type=int, default=60)
    return parser


def main() -> int:
    return asyncio.run(async_main(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
