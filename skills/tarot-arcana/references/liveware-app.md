# Liveware Web App

The liveware web app is an optional browser interface. It does not replace the agent's interpretation.

## First-time setup (setup.py)

`setup.py` handles all three registration steps — login, app creation, and ClawChat registration:

```bash
cd <skill-dir>
python3 scripts/liveware/setup.py
```

The script:
1. Calls `tools.liveware_login()` via the ClawChat plugin (no manual token handling)
2. Runs `liveware app list` first to check for an existing app, then `liveware app create` if needed
3. Calls `tools.register_app()` to register with ClawChat (URL constructed from app ID)

On success it prints `APP_ID=<id>` — pass this to start.sh.

## Daily activation (start.sh)

After setup, or when tarot is already registered, start the server and bind the tunnel:

```bash
cd <skill-dir>
bash scripts/liveware/start.sh <app-id>
```

The app ID is required. When called from the boot handler (`handler.py`'s `_start_tarot_liveware`), it passes the app ID as the first argument automatically.

## Responsibilities

| Script | Steps |
|--------|-------|
| `setup.py` | login → create app → register to ClawChat |
| `start.sh` | start server → bind tunnel |
