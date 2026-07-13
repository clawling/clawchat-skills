#!/usr/bin/env python3
"""First-time install/activation of Liveware for Office preview directory.

Idempotent setup: login → create app → register to ClawChat.
Uses the ClawChat plugin's internal credential (not env vars) for login and registration."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

# Add ClawChat plugin to Python path so clawchat_gateway is importable
# Script is at: {HERMES_HOME}/skills/productivity/clawchat-officecli/scripts/setup.py
# Plugin is at: {HERMES_HOME}/plugins/clawchat
_PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "plugins" / "clawchat"
if _PLUGIN_DIR.exists():
    sys.path.insert(0, str(_PLUGIN_DIR))

# ── paths ──────────────────────────────────────────────────────────────
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
LIVE_HOME = Path(os.environ.get("OFFICE_LIVE_HOME") or HERMES_HOME / "workspace" / "office-live")
STATE_DIR = Path(os.environ.get("OFFICE_LIVE_STATE_DIR") or LIVE_HOME / ".state")
STATE_FILE = STATE_DIR / "liveware.env"
SCRATCH_DIR = STATE_DIR / "scratch"
APP_NAME = "OfficeCLI-Live"
LIVEWARE_BIN = os.environ.get("LIVEWARE_BIN") or "liveware"
LIVEWARE_DOMAIN = os.environ.get("LIVEWARE_DOMAIN") or "apps.clawling.io"
APP_ID = os.environ.get("OFFICE_APP_ID", "")


# ── helpers ────────────────────────────────────────────────────────────

def info(msg: str) -> None:
    print(f"[setup] {msg}", file=sys.stderr)


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> None:
    global APP_ID
    if APP_ID:
        return
    if STATE_FILE.exists():
        for line in STATE_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("OFFICE_APP_ID="):
                APP_ID = line.split("=", 1)[1].strip()
                break


def save_state(app_id: str) -> None:
    STATE_FILE.write_text(f"OFFICE_APP_ID={app_id}\n", encoding="utf-8")
    info(f"Saved OFFICE_APP_ID={app_id}")


def require_liveware() -> None:
    try:
        subprocess.run(
            [LIVEWARE_BIN, "--help"],
            capture_output=True, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        info("liveware CLI not found. Install liveware or set LIVEWARE_BIN.")
        sys.exit(1)


def run_liveware(*args: str) -> str:
    result = subprocess.run(
        [LIVEWARE_BIN, *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"liveware {' '.join(args)} failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def find_existing_app() -> str:
    """Return the app id of an existing app named APP_NAME, or empty string."""
    try:
        raw = run_liveware("app", "list", "--json")
    except RuntimeError:
        raw = run_liveware("app", "list")
    # Parse JSON if available
    try:
        items = json.loads(raw)
        if isinstance(items, dict):
            for key in ("apps", "data", "items"):
                items = items.get(key, items)
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("NAME") or ""
                if name == APP_NAME:
                    return str(item.get("id") or item.get("appId") or item.get("app_id") or "")
            # fallback: first app
            for item in items:
                if isinstance(item, dict):
                    aid = item.get("id") or item.get("appId") or item.get("app_id") or ""
                    if aid:
                        return str(aid)
    except (json.JSONDecodeError, TypeError):
        pass
    # Text fallback: regex for app-xxx
    import re
    match = re.search(r"app[-_][A-Za-z0-9][A-Za-z0-9_-]*", raw)
    return match.group(0) if match else ""


def create_app() -> str:
    """Create a liveware app and return its id."""
    info(f"Creating liveware app: {APP_NAME}")
    # Try with --agent-type hermes first
    try:
        raw = run_liveware("app", "create", APP_NAME, "--agent-type", "hermes")
    except RuntimeError:
        raw = run_liveware("app", "create", APP_NAME)
    # Extract app id from output
    import re
    match = re.search(r"app[-_][A-Za-z0-9][A-Za-z0-9_-]*", raw)
    if match:
        return match.group(0)
    # Fallback: check list
    existing = find_existing_app()
    if existing:
        return existing
    raise RuntimeError(
        f"Could not determine app id from liveware output:\n{raw}"
    )


# ── async setup (uses plugin tools) ────────────────────────────────────

async def setup() -> int:
    global APP_ID
    ensure_dirs()
    load_state()
    require_liveware()

    # ── 1. Login via plugin tool ──
    info("Logging in to liveware…")
    from clawchat_gateway.tools import liveware_login

    login_result = await liveware_login()
    if login_result.get("ok"):
        info("Liveware auth: ok")
    else:
        err = login_result.get("error") or "unknown"
        msg = login_result.get("message") or str(login_result)
        info(f"Liveware login failed ({err}): {msg}")
        return 1

    # ── 2. Find or create app ──
    if APP_ID:
        info(f"Using existing app: {APP_ID}")
    else:
        existing = find_existing_app()
        if existing:
            APP_ID = existing
            info(f"Using existing app: {APP_ID}")
        else:
            APP_ID = create_app()
            info(f"Created app: {APP_ID}")
    save_state(APP_ID)

    # ── 3. Register to ClawChat via plugin tool ──
    url = f"https://{APP_ID}.{LIVEWARE_DOMAIN}"
    info(f"Registering app to ClawChat: {url}")
    from clawchat_gateway.tools import register_app

    reg_result = await register_app(name=APP_NAME, app_id=APP_ID, url=url)
    if isinstance(reg_result, dict) and reg_result.get("error"):
        err = reg_result["error"]
        msg = reg_result.get("message") or str(reg_result)
        info(f"ClawChat registration failed ({err}): {msg}")
        return 1
    info(f"Registered app \"{APP_NAME}\" ({APP_ID}) to ClawChat: {url}")

    return 0


def main() -> int:
    return asyncio.run(setup())


if __name__ == "__main__":
    sys.exit(main())
