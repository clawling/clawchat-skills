# OfficeCLI Liveware

Use this reference when a user needs the OfficeCLI preview directory exposed through
Liveware. Liveware lifecycle scripts live under `${HERMES_SKILL_DIR}/liveware/scripts`.

## Scripts

| Script | When to use |
| --- | --- |
| `liveware/scripts/setup.py` | Prepare the Liveware app and ClawChat registration |
| `liveware/scripts/start.sh` | Start/check the preview directory and bind the tunnel |
| `scripts/office-live-directory-launch.sh` | Server-only lifecycle adapter used by `start.sh` |
| `scripts/office-liveware-server-only.sh` | Preserved Office directory lifecycle and logging implementation |
| `scripts/office-live-directory.py` | Directory server invoked by the adapter |

## Setup

Run setup before the first preview session, or when authentication or app creation is
not prepared yet:

```bash
python3 ${HERMES_SKILL_DIR}/liveware/scripts/setup.py
```

The start script does NOT call setup automatically — run setup first, then start:

```bash
python3 ${HERMES_SKILL_DIR}/liveware/scripts/setup.py
PORT=26316 bash ${HERMES_SKILL_DIR}/liveware/scripts/start.sh
```

Useful environment variables:

- `OFFICE_LIVE_HOME`: workflow home, default `${HERMES_HOME:-$HOME/.hermes}/workspace/office-live`.
- `LIVEWARE_BIN`: Liveware binary name or path, default `liveware`.
- `LIVEWARE_DOMAIN`: Liveware public URL domain suffix, default `apps.clawling.io`.
- `HERMES_HOME`: Hermes home directory, optional — falls back to `$HOME/.hermes` when unset.

## Start

Run start directly when the user needs the browser preview directory. Do not ask
the user to perform setup before trying this script.

```bash
PORT=26316 bash ${HERMES_SKILL_DIR}/liveware/scripts/start.sh
```

If start fails, run setup once and then run start again:

```bash
python3 ${HERMES_SKILL_DIR}/liveware/scripts/setup.py
PORT=26316 bash ${HERMES_SKILL_DIR}/liveware/scripts/start.sh
```

Only ask the user for help when Liveware authentication credentials are missing
or an interactive login is required.

Useful environment variables:

- `OFFICE_LIVE_HOME`: workflow home, default `${HERMES_HOME:-$HOME/.hermes}/workspace/office-live`.
- `OFFICE_DOC_ROOTS`: colon-separated document roots, default `${OFFICE_LIVE_HOME}/documents`.
- `OFFICE_DIRECTORY_PORT`: local directory service port.
- `OFFICE_DIRECTORY_SCRIPT`: alternate path to `office-live-directory.py`.
- `OFFICE_DIRECTORY_LOG`: directory service log path.
- `LIVEWARE_BIN`: Liveware binary name or path, default `liveware`.
- `LIVEWARE_DOMAIN`: Liveware public URL domain suffix, default `apps.clawling.io`.
- `HERMES_HOME`: Hermes home directory, optional — falls back to `$HOME/.hermes` when unset.

## Expected State

- User-facing Office files: `${OFFICE_DOC_ROOTS:-${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/documents}`
- Runtime state and logs: `${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/.state`
- Liveware app state: `$HOME/.clawling/apps/clawchat-officecli.json`

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
- Liveware setup script: `${HERMES_SKILL_DIR}/liveware/scripts/setup.py`
- Liveware start script: `${HERMES_SKILL_DIR}/liveware/scripts/start.sh`
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


## Verification

- `curl -fsS http://127.0.0.1:26316/healthz` returns `ok`.
- `curl -fsS http://127.0.0.1:26316/api/files` returns preview-directory JSON.
- Opening `/preview/<doc-id>/` returns the wrapper page.
- Opening `/preview/<doc-id>/_watch/` returns the OfficeCLI watch page.

## Agent Flow

1. Use the Python setup script (`setup.py`) for account, authentication, or app id
   preparation and ClawChat registration.
2. Use the start script (`start.sh`) to expose the preview directory.
3. Share the printed public URL with the user.
4. For Office document creation, editing, reading, formatting, and validation, route to
   the most specific official OfficeCLI skill.
