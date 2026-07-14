---
name: clawchat-officecli
description: Use this skill when Hermes needs to work with OfficeCLI in ClawChat, route Office document tasks to official OfficeCLI skills, read browser-selected Office content, manage the Office document root, or start the Liveware preview directory.
---

# Clawchat OfficeCLI

Use this skill to guide OfficeCLI usage in ClawChat and to expose an OfficeCLI
preview directory through Liveware. For Office document content work, route to
the most specific official OfficeCLI skill first, then use the OfficeCLI CLI or
MCP exactly as that official skill instructs. Liveware is only the browser
preview and file-directory layer.

## Primary Rule

When the user asks to create, read, inspect, edit, format, summarize, validate,
or continue work on an Office document, use OfficeCLI. Do not use Liveware,
directory JSON APIs, or watch HTTP endpoints as the document API.

Use this order:

1. Select the most specific official OfficeCLI skill for the task.
2. Resolve `OFFICE_BIN` and set `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`.
3. Locate or create the target file in the managed document root.
4. Use OfficeCLI commands or OfficeCLI MCP for document reads and writes.
5. Use Liveware only when the user wants a browser preview or file directory.

OfficeCLI command bootstrap:

```bash
HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
OFFICE_BIN="${OFFICE_BIN:-$(command -v officecli || true)}"
OFFICE_BIN="${OFFICE_BIN:-$HOME/.local/bin/officecli}"
if [ ! -x "$OFFICE_BIN" ] && [ -x "${HERMES_HOME}/home/.local/bin/officecli" ]; then OFFICE_BIN="${HERMES_HOME}/home/.local/bin/officecli"; fi
DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" --help
```

Common OfficeCLI commands:

```bash
DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" create "$DOC"
DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" get "$DOC" "/" --json
DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" get "$DOC" selected --json
DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" query "$DOC" "p" --json
DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" set "$DOC" "/body/p[1]" --prop text="Updated text"
DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" add "$DOC" "/body" --type p --prop text="New paragraph"
DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" remove "$DOC" "/body/p[2]"
DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" batch "$DOC" --commands "$COMMANDS_JSON"
DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" validate "$DOC" --json
```

Selection workflow:

1. Ask the user to click or select content in the browser preview.
2. Read the current selection with:

   ```bash
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" get "$DOC" selected --json
   ```

3. Modify the selected node with the official OfficeCLI skill's recommended
   `set`, `add`, `remove`, or `batch` command.
4. Do not call `/api/selection`.

## Scope

Use this skill to:

- Guide agents to use official OfficeCLI skills and OfficeCLI commands.
- Read browser-selected preview content through `officecli get <file> selected --json`.
- Choose and enforce the managed Office file directory.
- Start the browser preview directory.
- List managed `.docx`, `.pptx`, and `.xlsx` files.
- Route document work to the most specific official OfficeCLI skill.
- Keep runtime state and logs out of document directories.

## Requirements

Install and verify these before using the preview-directory workflow.

Required:

1. Install OfficeCLI and set `OFFICE_BIN` to the actual binary path.

   ```bash
   INSTALL_DIR="${HERMES_HOME}/workspace/office-live/.state/scratch"
   mkdir -p "$INSTALL_DIR"
   OFFICECLI_INSTALLER="$INSTALL_DIR/officecli-install.sh"
   curl -fsSL https://d.officecli.ai/install.sh -o "$OFFICECLI_INSTALLER"
   bash "$OFFICECLI_INSTALLER"
   OFFICE_BIN="${OFFICE_BIN:-$(command -v officecli || true)}"
   OFFICE_BIN="${OFFICE_BIN:-$HOME/.local/bin/officecli}"
   if [ ! -x "$OFFICE_BIN" ] && [ -x "$HERMES_HOME/home/.local/bin/officecli" ]; then OFFICE_BIN="$HERMES_HOME/home/.local/bin/officecli"; fi
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" --help
   ```

   Always run OfficeCLI with `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` in this container.

2. Install the official OfficeCLI Hermes skills.

   ```bash
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills hermes
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills install word hermes
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills install pptx hermes
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills install excel hermes
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills install word-form hermes
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills install morph-ppt hermes
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills install morph-ppt-3d hermes
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills install pitch-deck hermes
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills install academic-paper hermes
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills install data-dashboard hermes
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills install financial-model hermes
   ```

   Check available official skills with:

   ```bash
   DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills list
   ```

3. Install this skill and its scripts in a Hermes skill directory and run it through
   `${HERMES_SKILL_DIR}`.

Recommended:

- Configure OfficeCLI MCP as server `officecli` in the Hermes config file.
- Restart Hermes Agent after adding or changing MCP config so MCP tools are discovered.
- Use MCP for structured OfficeCLI operations when available, while still following
  the matching official OfficeCLI skill.

## Official Skill Routing

Before any Office document operation, choose the most specific official OfficeCLI skill.
Task-specific skills take precedence over file-format skills.

| User request | Official skill to use first |
| --- | --- |
| Form or structured Word form | `officecli-word-form` |
| Pitch deck | `officecli-pitch-deck` |
| Academic paper | `officecli-academic-paper` |
| Data dashboard | `officecli-data-dashboard` |
| Financial model | `officecli-financial-model` |
| PowerPoint morph animation | `morph-ppt` or `morph-ppt-3d` |
| Generic Word document | `officecli-docx` |
| Generic PowerPoint deck | `officecli-pptx` |
| Generic Excel workbook | `officecli-xlsx` |

Rules:

1. Use this skill only for workspace location, preview-directory startup, and file listing.
2. Use the selected official skill for creation, editing, reading, formatting, schema paths, save behavior, and validation.
3. Treat official OfficeCLI skills as the source of truth for document operations.
4. Do not use `hermes send` for ClawChat delivery from Liveware or directory-server processes.
5. If no official skill appears to fit, inspect the installed official OfficeCLI skills before inventing a document workflow.

## Liveware Reference

Liveware service details are intentionally kept out of this main skill. When the
user needs browser preview, file-directory UI, Liveware setup, tunnel binding,
directory-server state, or preview troubleshooting, read:

```bash
${HERMES_SKILL_DIR}/references/officecli-liveware.md
```

Use the bundled scripts described there. Do not ask the user to complete preview
setup before trying the start script.

## List Managed Files

When the user asks which Office files are available, list the managed document root first:

```bash
DOC_ROOT="${OFFICE_DOC_ROOTS:-${OFFICE_LIVE_HOME:-$HERMES_HOME/workspace/office-live}/documents}"
find "$DOC_ROOT" -maxdepth 1 -type f \( -name '*.docx' -o -name '*.pptx' -o -name '*.xlsx' \) -print
```

Search the managed document root before considering user-provided additional roots.

## Bundled Files

Hermes installation must include every runtime support file below:

- `assets/web/assets/app-CRMN-Ydz.js`
- `assets/web/assets/index-CjYUnOjr.css`
- `assets/web/index.html`
- `assets/web/preview-error.html`
- `references/officecli-liveware.md`
- `scripts/office-live-directory.py`
- `scripts/office-liveware-setup.py`
- `scripts/office-liveware-start.sh`

## Agent Workflow

1. Select the most specific official OfficeCLI skill for the requested document work.
2. Follow that official skill for all document operations.
3. List managed Office files from the document root when file discovery is needed.
4. Identify the target file or ask the user to choose one.
5. Read `references/officecli-liveware.md` only when Liveware account, app, tunnel, preview startup, or preview-directory troubleshooting is needed.
6. Keep files in the managed document root unless the user explicitly provides another clean workspace.
