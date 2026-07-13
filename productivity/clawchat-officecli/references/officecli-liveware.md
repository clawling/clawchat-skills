# OfficeCLI Liveware

Use this reference when a user needs the OfficeCLI preview directory exposed through
Liveware. Use the bundled scripts from `${HERMES_SKILL_DIR}/scripts`.

## Script Responsibilities

- `office-liveware-setup.py` (primary): Python script that handles first-time
  setup — logs in to liveware via the ClawChat plugin's internal credential
  store, creates or reuses a liveware app, and **registers the app to ClawChat**
  using plugin tools.
  Stores app id in `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/.state/liveware.env`.
- `office-liveware-start.sh`: starts the local Office preview directory service
  on the given port, binds the app to the local service through `liveware tunnel
  bind`, and prints the public URL. Does NOT handle setup or registration —
  those are the responsibility of `setup.py`.
- `office-live-directory.py`: serves the Office file directory and proxies each
  file preview to an OfficeCLI watch server.

## Setup

Run setup before the first preview session, or when authentication or app creation is
not prepared yet. The Python setup script handles login, app creation, and ClawChat registration
using plugin tools:

```bash
${HERMES_SKILL_DIR}/scripts/office-liveware-setup.py
```

The start script does NOT call setup automatically — if the app id is missing,
start.sh will error out. Run setup first, then start:

```bash
${HERMES_SKILL_DIR}/scripts/office-liveware-setup.py
${HERMES_SKILL_DIR}/scripts/office-liveware-start.sh 26316
```

Useful environment variables:

- `OFFICE_LIVE_HOME`: workflow home, default `${HERMES_HOME:-$HOME/.hermes}/workspace/office-live`.
- `OFFICE_APP_ID`: reuse a known Liveware app id.
- `OFFICE_APP_NAME`: **Deprecated** — app name is now hardcoded as `OfficeCLI-Live` in `setup.py`.
  Setting this variable has no effect.
- `LIVEWARE_TOKEN`: an already exchanged Liveware control-plane token. The Liveware CLI
  consumes it directly; do not pass it to `liveware login --access-token`.
- `OFFICE_LIVEWARE_INSTALL_CMD`: explicit command to install Liveware when it is missing.
- `OFFICE_LIVEWARE_INSTALL_URL`: install script URL for Liveware when it is missing.
- `LIVEWARE_BIN`: Liveware binary name or path, default `liveware`.
- `LIVEWARE_DOMAIN`: Liveware public URL domain suffix, default `apps.clawling.io`.
- `HERMES_HOME`: Hermes home directory, optional — falls back to `$HOME/.hermes` when unset.

**Note on ClawChat authentication**: The Python setup script (`setup.py`) uses the
ClawChat plugin's internal credential store for login and registration. It does
**not** use `$CLAWCHAT_TOKEN` or `$CLAWCHAT_ACCESS_TOKEN` — those env vars are not
the correct credentials for the ClawChat REST API. The plugin handles authentication
internally via `clawchat_liveware_login()` and `clawchat_register_app()`.

## Start

Run start directly when the user needs the browser preview directory. Do not ask
the user to perform setup before trying this script.

```bash
${HERMES_SKILL_DIR}/scripts/office-liveware-start.sh 26316
```

The start script:

1. Creates `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/documents` when needed.
2. Starts the directory service on the requested local port.
3. Reads the app id from the state file (`liveware.env`); errors out if missing.
4. Binds the Liveware app to `http://127.0.0.1:<port>`.
5. Prints the public directory URL.

If start fails, run setup once and then run start again:

```bash
${HERMES_SKILL_DIR}/scripts/office-liveware-setup.py
${HERMES_SKILL_DIR}/scripts/office-liveware-start.sh 26316
```

Only ask the user for help when Liveware authentication credentials are missing
or an interactive login is required.

Useful environment variables:

- `OFFICE_LIVE_HOME`: workflow home, default `${HERMES_HOME:-$HOME/.hermes}/workspace/office-live`.
- `OFFICE_DOC_ROOTS`: colon-separated document roots, default `${OFFICE_LIVE_HOME}/documents`.
- `OFFICE_APP_ID`: reuse a known Liveware app id.
- `OFFICE_DIRECTORY_PORT`: local directory service port.
- `OFFICE_DIRECTORY_SCRIPT`: alternate path to `office-live-directory.py`.
- `OFFICE_LIVEWARE_SETUP_SCRIPT`: alternate path to `office-liveware-setup.py`.
  Not used by `start.sh` — `start.sh` does not call setup.
- `OFFICE_DIRECTORY_LOG`: directory service log path.
- `LIVEWARE_BIN`: Liveware binary name or path, default `liveware`.
- `LIVEWARE_DOMAIN`: Liveware public URL domain suffix, default `apps.clawling.io`.
- `HERMES_HOME`: Hermes home directory, optional — falls back to `$HOME/.hermes` when unset.

App name is `OfficeCLI-Live` (hardcoded in `setup.py`, not configurable).

## Expected State

- User-facing Office files: `${OFFICE_DOC_ROOTS:-${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/documents}`
- Runtime state and logs: `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/.state`
- Liveware app id state: `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/.state/liveware.env`

Use these directories consistently:

| Purpose | Directory |
| --- | --- |
| Workflow home | `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}` |
| User-facing Office files | `${OFFICE_DOC_ROOTS:-${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/documents}` |
| Optional source data/assets | `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/assets` |
| Optional exports | `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/exports` |
| Skill implementation | `${HERMES_SKILL_DIR}` |
| Directory service state, PIDs, and logs | `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/.state` |
| Temporary scratch files | `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/.state/scratch` |

Directory rules:

- Keep user-facing `.docx`, `.pptx`, and `.xlsx` files under the managed document root by default.
- Avoid the Docker mount root, container root, hidden directories, credential directories, logs, sessions, or skill installation directories as document roots.
- Keep runtime state out of the document root.
- Only scan additional directories when the user explicitly asks; pass them with `OFFICE_DOC_ROOTS=/path/a:/path/b`.

## Service Paths

- OfficeCLI binary: `${OFFICE_BIN:-officecli}`; if `officecli` is not on `PATH`, set `OFFICE_BIN` to the installed binary path.
- Liveware setup script (primary): `${HERMES_SKILL_DIR}/scripts/office-liveware-setup.py`
- Liveware start script: `${HERMES_SKILL_DIR}/scripts/office-liveware-start.sh`
- Directory server: `${HERMES_SKILL_DIR}/scripts/office-live-directory.py`
- Liveware script reference: `${HERMES_SKILL_DIR}/references/officecli-liveware.md`
- Default workflow home: `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}`
- Default document root: `${OFFICE_DOC_ROOTS:-${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/documents}`
- Runtime state and logs: `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/.state`

## Safe Inspection

Use the directory server JSON API to inspect files and preview-directory state:

```bash
curl -fsS http://127.0.0.1:26316/api/files
```

Use direct `curl` output, `grep`, or file reads for simple checks. Avoid piping
HTTP responses into interpreters such as `python`, `python3`, `node`, `bash`, or
`sh`; Hermes may require approval for that pattern because it resembles remote
code execution.

Do not use directory or watch HTTP APIs to inspect Office document content or
current browser selection. For selected preview content, use the official
OfficeCLI command:

```bash
DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" get "$DOC" selected --json
```

## ClawChat Messages

When the browser prepares a file message for ClawChat, deliver it from the Hermes
agent with the `send_message` tool. The prepared message must include
`MEDIA:<absolute-file-path>` for the Office file so ClawChat receives a native
attachment, not only a preview link.

Rules:

- Do not hard-code a ClawChat chat ID in source code.
- Do not use `hermes send` or the directory server to deliver the message.
- Do not call the directory server or Liveware to send ClawChat messages.

Recent share requests can be inspected with:

```bash
curl -fsS http://127.0.0.1:26316/api/share-requests?limit=20
```

## Troubleshooting

- If OfficeCLI exits with an ICU error, rerun with `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`.
- If the preview directory does not open, run the launcher again and check `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/.state/directory.log`.
- If a document is missing from the directory, place it under one of `OFFICE_DOC_ROOTS` or start the launcher with `OFFICE_DOC_ROOTS=/path/a:/path/b`.
- If preview selection is not recorded, confirm the browser request to `/preview/<doc-id>/_watch/api/selection` returns `204`, then read the selected node with OfficeCLI.
- If Hermes asks for command approval after `curl-to-python piping`, do not approve that command. Use direct `curl`, `grep`, or OfficeCLI instead.
- If duplicate Liveware apps appear (same name, different IDs), the `existing_app_id()` name matching in `office-liveware-setup.py` may have failed. Run `liveware app list`, identify duplicates, delete extras with `liveware app delete <id>`. The correct app ID is stored in `.state/liveware.env`.
- If registration fails with `invalid token`, the script is likely using `$CLAWCHAT_TOKEN` or curl instead of plugin tools. Only `setup.py` can register via `clawchat_register_app()`. Shell scripts and curl will always fail.

## Verification

- `curl -fsS http://127.0.0.1:26316/healthz` returns `ok`.
- `curl -fsS http://127.0.0.1:26316/api/files` returns preview-directory JSON.
- Opening `/preview/<doc-id>/` returns the wrapper page.
- Opening `/preview/<doc-id>/_watch/` returns the OfficeCLI watch page and records a watch in `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/.state/state.json`.
- Browser selection posts to `/preview/<doc-id>/_watch/api/selection` with status `204`.

## Agent Flow

1. Use the Python setup script (`setup.py`) for account, authentication, or app id
   preparation and ClawChat registration.
2. Use the start script (`start.sh`) to expose the preview directory.
3. Share the printed public URL with the user.
4. For Office document creation, editing, reading, formatting, and validation, route to
   the most specific official OfficeCLI skill.
