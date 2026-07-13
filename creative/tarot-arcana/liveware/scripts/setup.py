#!/usr/bin/env python3
"""Tarot Arcana — first-time setup

Responsibility: login → create app → register to ClawChat
Usage: python3 setup.py

Output:
  APP_ID=<id>     — liveware app ID
  APP_URL=<url>   — public tunnel URL

After setup.py succeeds, the caller should run start.sh to start the server and tunnel.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# ── Ensure clawchat_gateway is importable ────────────────────
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
_PLUGIN_DIR = _HERMES_HOME.parent / "plugins" / "clawchat"
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

try:
    from clawchat_gateway import tools
except ImportError:
    print("❌ Cannot import clawchat_gateway.tools — make sure the ClawChat plugin is installed")
    sys.exit(1)

APP_NAME = "Tarot Arcana"
_APP_ID_RE = re.compile(
    r"app[ _-]?id\b\s*[:=]?\s*\"?([A-Za-z0-9][A-Za-z0-9_-]*)\"?",
    re.IGNORECASE,
)


def _find_existing_app() -> str | None:
    """Check if a tarot app already exists; return app ID or None."""
    result = subprocess.run(
        ["liveware", "app", "list"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        haystack = line.lower()
        if "tarot" not in haystack and "arcana" not in haystack:
            continue
        # Try to extract app ID from the line
        m = _APP_ID_RE.search(line)
        if m:
            return m.group(1)
    return None


def _create_app() -> str | None:
    """Create a liveware app; return app ID or None."""
    print("📦 Creating app...")
    result = subprocess.run(
        ["liveware", "app", "create", APP_NAME, "--agent-type", "hermes"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"   ❌ Failed to create: {result.stderr.strip()}")
        return None

    m = _APP_ID_RE.search(result.stdout)
    if m:
        app_id = m.group(1)
        print(f"   ✅ App ID: {app_id}")
        return app_id

    print(f"   ❌ Could not parse app ID from output:\n{result.stdout[:500]}")
    return None


async def main() -> bool:
    # ── 1. Login ──────────────────────────────────────────
    print("🔑 Logging in to liveware...")
    result = await tools.liveware_login()
    if not result.get("ok"):
        print(f"   ❌ Login failed: {result}")
        return False
    print("   ✅ Logged in")
    print()

    # ── 2. Create app ─────────────────────────────────────
    app_id = _find_existing_app()
    if app_id:
        print(f"📦 Found existing app: {app_id}")
    else:
        app_id = _create_app()
        if not app_id:
            return False
    print()

    # ── 3. Register to ClawChat ───────────────────────────
    app_url = f"https://{app_id}.apps.clawling.io"
    print("🔗 Registering with ClawChat...")
    result = await tools.register_app(
        name=APP_NAME,
        app_id=app_id,
        url=app_url,
    )
    if result.get("error"):
        print(f"   ❌ Registration failed: {result}")
        return False
    print("   ✅ Registered")
    print()

    # ── Output for the caller ──────────────────────────────
    print("═══════════════════════════════════════════")
    print("✅ Tarot setup complete")
    print(f"   APP_ID={app_id}")
    print(f"   APP_URL={app_url}")
    print("═══════════════════════════════════════════")
    print()
    print("👉 Now run start.sh to start the server + tunnel:")
    print(f"   bash {Path(__file__).parent}/start.sh {app_id}")
    return True


if __name__ == "__main__":
    import asyncio

    success = asyncio.run(main())
    sys.exit(0 if success else 1)
