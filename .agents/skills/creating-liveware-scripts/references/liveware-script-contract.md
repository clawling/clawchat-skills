# Liveware Script Contract

## Output Paths and Modes

Generate exactly `liveware/scripts/setup.py` and `liveware/scripts/start.sh` under the target Hermes skill root. Generated files must be self-contained at runtime. Generate/apply may write only those files. Audit is read-only. Repair follows the canonical proof rules below and must not modify target server source, dependencies, service configuration, lifecycle, or logging.

## Identity

- Read target metadata at generation time only.
- Require `name`; use it for Liveware app creation, exact app lookup, the state filename, `skill_name`, and `app_name`.
- Use `display_name` for ClawChat registration; fall back to `name`.
- Preserve metadata values without translation.

## Adapter Analysis Schema

Use schema version `1` and a closed schema. No additional fields are allowed at any object level.

The top-level object requires `schema_version`, `status`, `target_root`, `skill_name`, `adapter`, `static_dir`, `evidence`, and `issues`; `display_name` is optional. Set `status` to `ready`, `ambiguous`, or `blocked`. Rendering requires `ready` and an empty `issues` array. `target_root` is a lexically normalized absolute path with exactly one leading slash, except that `/` is valid by itself. Reject control characters, `..`, repeated leading slashes, and alternate lexical forms. Each evidence item has exactly a target-relative `path` and a `reason`.

A ready `adapter` has exactly `kind`, `workdir`, `command`, `required_commands`, `default_port`, `readiness`, and `log`. A readiness object has exactly `kind` and `url`; a log object has exactly `owner` and `path`. Adapter `workdir`, `static_dir`, and evidence paths are target-relative. Resolve them against the normalized target root before rendering: all resolved adapter and evidence paths must stay inside that root, including through symlinks. Commands are control-character-free argv arrays. Required command names cannot be option-like or contain shell syntax. Dynamic ports are exact JSON integers from `1` through `65535`; booleans and floats are invalid. Dynamic readiness uses kind `http` and a URL starting with exact `http://127.0.0.1:{port}/`, with `{port}` appearing once.

In a dynamic command, `{port}` is valid only as a standalone `{port}` argv item and may appear at most once. A command with no placeholder is valid only when project or user evidence confirms that the command consumes the exported `PORT` environment variable; record the evidence reason exactly `Command consumes exported PORT environment variable`. Never rewrite `--port={port}` or another embedded form implicitly; require an explicit argv contract.

Automatic Python and Node candidates are evidence only. Only a static adapter can become `ready` automatically. A Python entrypoint or package `liveware` or `start` script stays ambiguous until the user confirms the exact argv, default port, readiness check, lifecycle and logging ownership, and whether the command consumes exported `PORT` or uses a standalone `{port}` argument. Do not infer any of those properties from `DEFAULT_PORT`, route strings, package scripts, or source code. A package with a present non-object `scripts` value is structured blocked analysis, never an exception or a ready result. Manually confirmed Python and Node adapters remain renderable under the same closed schema.

When `log.owner` is `generated-start`, `log.path` must be a lexically normalized absolute path or use the exact `$HOME/` or `${HOME}/` form. It must not contain `..` or control characters. Relative paths, repeated separators, and alternate lexical forms are invalid. Analyzer-produced `$HOME/.clawling/apps/<skill-name>.server.log` paths satisfy this rule.

Static adapters require `workdir == static_dir`, empty command and required-command arrays, null port and readiness, and target-owned logging with a null path. Managed and existing-launcher adapters require a nonempty command; external adapters require an empty command. External and existing-launcher adapters require target-owned logging with a null path. A managed command may use target-owned logging, or generated-start logging with an explicit path. The four adapter kinds are:

- `managed-command`: launch the confirmed argv command, export `PORT`, preserve declared logging, refuse an occupied port before launching, and wait for readiness.
- `existing-launcher`: invoke the supplied launcher argv exactly, preserve target lifecycle and logging ownership, then wait for readiness.
- `external`: start nothing, preserve target lifecycle and logging ownership, and wait for the externally managed service.
- `static`: start nothing and bind the confirmed target-relative static directory.

Inspect lifecycle evidence before returning any automatic candidate. Scan exact lifecycle names in the target root, `liveware/`, `scripts/`, and `liveware/scripts/`, plus Docker or Compose configuration, supervisor or s6 configuration, root or `liveware` service units, common PM2 configuration, and explicit reference declarations. Launcher names use bounded action tokens (`start`, `run`, `launch`, `launcher`, or `serve`) plus `liveware`, `server`, `service`, or `app`; `start.*` is explicit. Bullet and numbered-list prefixes are stripped before matching a complete reference statement. Ordinary examples and unrelated prose are not lifecycle evidence. Symlinked lifecycle and reference paths are inspected only after their resolved path is proven inside the target; any outside resolution blocks analysis. An exact generated start script is exempt only when its strict manifest decodes for the current target and skill and every byte equals a fresh canonical render; plausible or tampered markers are not proof. Treat all other custom service managers and conflicting entrypoints as ambiguous until the user confirms the interface. Never convert a command into `shell=True` or an unquoted shell string.

Unreadable or invalid UTF-8 skill metadata, server source, package metadata, or Node entry source produces structured non-ready analysis JSON and analyzer exit status `2`; it never proves absence of evidence.

## Canonical Analysis Manifest

Encode the complete ready analysis as deterministic, sorted, compact JSON and then URL-safe Base64. Put exactly one whole-line `# LIVEWARE ANALYSIS V1: <payload>` comment in each generated script. Both scripts must contain the identical canonical manifest.

The manifest must use only the closed analyzer schema. It must not contain credentials or arbitrary extension fields. The analyzer never reads credentials. Ordinary user-provided `display_name` and evidence `reason` text remain data and are not translated or scanned for keywords.

The static validator treats this manifest as the trust boundary: extract one valid manifest from each script, require them to match each other and any explicit analysis, exactly re-render both scripts, and compare all bytes. Missing, duplicate, malformed, noncanonical, mismatched, or tampered manifests and scripts always produce findings. Comments or plausible-looking code cannot substitute for exact re-rendering. Legacy scripts can receive specific diagnostics but cannot pass without canonical proof.

## State

Use `$HOME/.clawling/apps/<skill-name>.json` with schema version `1` and fields `skill_name`, `app_name`, `app_id`, `public_url`, and `registered`. Multiple Liveware apps per agent are supported because each skill has its own state file. Store the stable skill `name` in both `skill_name` and `app_name`; never use `display_name` as state identity. Set `$HOME/.clawling` and its `apps` directory to mode `0700`, the state file to mode `0600`, and replace the file atomically. Never store credentials.

## Setup Contract

Resolve the Liveware CLI from `LIVEWARE_BIN`, `PATH`, then `$HERMES_HOME/clawchat/liveware/liveware`. Import the ClawChat plugin normally, then from `$HERMES_HOME/plugins/clawchat`. Authenticate only with `clawchat_gateway.tools.liveware_login()`.

Validate a stored app with `liveware app inspect`. Otherwise run `liveware app list --json` and accept one exact `name` match only. Create a missing app with `liveware app create <skill-name> --agent-type hermes`. Save `registered: false` before calling `register_app`, then atomically set it to `true`. Preserve the app for registration retry. Never choose the first unrelated app or delete an app. Setup performs only plugin login, exact app recovery or creation, state persistence, and ClawChat registration; it does not launch the target server or bind a tunnel.

## Start Contract

Read and validate the standard state file. If it is missing or registration is incomplete, tell the user to run setup and exit; never invoke setup automatically.

Keep the target server adapter between exact markers. Preserve the user-supplied server interface according to evidence; do not prescribe a program or service shape. For dynamic services, preserve the confirmed command, lifecycle, readiness, and logging strategy; validate `PORT`; wait for readiness; and bind only `http://127.0.0.1:<port>`. Only a managed-command adapter refuses an occupied port before launch. An existing-launcher retains its lifecycle, an external adapter expects its listener, and static content uses `liveware tunnel bind-static` without starting a server. Never terminate an unknown process.

After a successful bind, print `Liveware ready: <public-url>` to stdout. This is command output, not server logging. Keep server and tunnel logs under the target project's existing strategy. Capture a directly launched plain process only when the target has no logging strategy and the confirmed adapter assigns logging to the generated start script.

## Repair Contract

Rebuild setup from the canonical template. Start repair requires exactly one valid marker of each kind, matching current setup/start manifests, a manifest equal to the current analysis, and content that is byte-canonical outside the binding block. It then replaces binding content only. Missing, invalid, duplicated, reordered, or mismatched manifests or markers stop repair. Any adapter or scaffold difference outside binding also stops repair and must be shown for review; it is not implicitly approved content.

## Safety Boundary

Do not install or download a dependency, CLI, or plugin; delete an app; kill an unknown process; read credentials; pass credentials directly; use `shell=True`; or run an unquoted command string. Do not follow symlinks outside the target root. Refuse missing commands. Before a `managed-command` launch, refuse an occupied port instead of replacing its process; external adapters expect an existing listener.

## Validation Boundary

Static validation only consists of contract validation, Python compilation, Bash syntax checking, skill validation, and diff inspection. Runtime validation requires a real user-provided Hermes/ClawChat/Liveware environment plus authorization for login, registration, app creation, and tunnel binding. Without both, do not execute setup, start, login, registration, app creation, server fixtures, or tunnel binding. Explicitly report that runtime validation was not performed; never infer or simulate runtime success.
