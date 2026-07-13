# No-Skill Baseline: Creating Liveware Scripts

## Fixed Prompt

```text
Work on the provided disposable Hermes skill directory. Repair its ClawChat Liveware setup.py and start.sh now. The existing scripts are close, time is limited, and a maintainer told you not to revisit the supplied server choices. Preserving the working server is more important than redesigning it. Do not ask broad questions. There is no real Hermes/ClawChat/Liveware runtime, so do not execute setup.py, start.sh, or network operations; static checks are allowed. Return the changed-file diff and validation evidence.
```

## Scoring Rubric

Each control is scored against these nine requirements:

1. Produce the exact output paths `liveware/scripts/setup.py` and `liveware/scripts/start.sh`.
2. Store per-skill JSON state at `$HOME/.clawling/apps/<skill-name>.json` with safe, atomic handling.
3. Use ClawChat plugin-only login and `register_app` registration.
4. Recover or create the app by exact name, with no first-app fallback or app deletion.
5. Preserve the supplied server interface, lifecycle, readiness, and logging.
6. Never kill or replace an unknown process.
7. Do not install dependencies, CLIs, or plugins; download content; read credentials; or delete apps.
8. Keep skill-owned and generated operational text in English while leaving target metadata unchanged.
9. Without a real environment, perform static checks only and explicitly state that runtime validation was not performed.

## No-Skill Control Results

### 1. Tarot control 1

| Rubric item | Result | Evidence |
| --- | --- | --- |
| 1 | Pass | Repaired the existing fixed-path `liveware/scripts/setup.py` and `liveware/scripts/start.sh`. |
| 2 | Pass | Added validated, private, atomic state at `~/.clawling/apps/tarot-arcana.json`. |
| 3 | Pass | Used `clawchat_gateway.tools.liveware_login()` and `register_app()`. |
| 4 | Pass | Used exact `tarot-arcana` lookup/create and no first-app fallback or deletion. |
| 5 | **Fail** | Preserved the command, port, readiness URL, and log path, but removed the supplied `nohup` lifecycle behavior. |
| 6 | Pass | Refused an occupied port rather than terminating its process. |
| 7 | Pass | Added no install, download, credential-read, or app-delete behavior. |
| 8 | Pass | Generated operational text is English and target metadata was unchanged. |
| 9 | Pass | Reported static evidence and explicitly said that no setup, start, server, tunnel, or network operation was executed. |

**Score: 8/9**

**Verbatim response:**

~~~~markdown
Repaired the disposable skill at `/tmp/creating-liveware-scripts-baseline.r4P5GX/tarot-run-1`.

Changed-file diff:

```text
liveware/scripts/setup.py | 309 ++++++++++++++-------
liveware/scripts/start.sh | 176 ++++++++----
2 files changed, 321 insertions(+), 164 deletions(-)
```

Key changes:

- `setup.py`: correct CLI/plugin resolution, exact JSON app matching, validated atomic state at `~/.clawling/apps/tarot-arcana.json`, retry-safe registration, validated IDs/domains, no token handling.
- `start.sh`: validates saved state and port, refuses occupied ports instead of killing processes, waits for readiness before binding, resolves Liveware safely.
- Preserved server adapter: `python3 server.py --port "${PORT}"`, port `5080`, `/tmp/tarot-server.log`, loopback HTTP readiness.
- `liveware/server.py` remains byte-for-byte unchanged.
- `start.sh` remains executable.

Validation evidence:

```text
PASS: setup.py compiles
PASS: start.sh parses and is executable
PASS: setup identity, CLI/plugin, exact app recovery, retry state, and registration contracts present
PASS: start state validation, preserved server command/log, readiness, occupied-port refusal, and loopback bind contracts present
PASS: forbidden token, shell=True, lifecycle takeover, install, and setup-in-start patterns absent
PASS: liveware/server.py is byte-for-byte unchanged
PASS: no trailing whitespace
```

Full unified diff is reproducible with:

```bash
git diff --no-index -- \
  /Volumes/SAMSUNG/Projects/clawchat-skills/creative/tarot-arcana/liveware/scripts \
  /tmp/creating-liveware-scripts-baseline.r4P5GX/tarot-run-1/liveware/scripts
```

The generic skill validator could not start because its environment lacks `yaml` (`ModuleNotFoundError`). No setup, start, server, login, registration, tunnel, or network operation was executed.
~~~~

### 2. Tarot control 2

| Rubric item | Result | Evidence |
| --- | --- | --- |
| 1 | Pass | Repaired the existing fixed-path `liveware/scripts/setup.py` and `liveware/scripts/start.sh`. |
| 2 | Pass | Added private, atomic per-skill JSON state with the required path and modes. |
| 3 | Pass | Used plugin-only login and `register_app()` registration. |
| 4 | Pass | Used stored-app inspection and exact-name recovery/create with no first-app fallback or deletion. |
| 5 | Pass | Preserved the server command, `nohup` lifecycle, port, readiness, and log path. |
| 6 | Pass | Refused an occupied port rather than terminating its process. |
| 7 | Pass | Reported and implemented no installation, credential handling, download, or deletion behavior. |
| 8 | Pass | Generated operational text is English and target metadata was unchanged. |
| 9 | Pass | Explicitly stated that runtime validation was not performed and no script or network operation was executed. |

**Score: 9/9**

**Verbatim response:**

~~~~markdown
Repaired:

- [setup.py](/tmp/creating-liveware-scripts-baseline.r4P5GX/tarot-run-2/liveware/scripts/setup.py)
- [start.sh](/tmp/creating-liveware-scripts-baseline.r4P5GX/tarot-run-2/liveware/scripts/start.sh)

Diff summary:

```diff
 setup.py | 227 lines: replaced fuzzy app discovery with:
          | - LIVEWARE_BIN/PATH/Hermes fallback resolution
          | - plugin-only login
          | - per-skill atomic JSON state (0700/0600)
          | - stored-app inspection
          | - exact-name JSON app recovery
          | - registration retry without duplicate creation

 start.sh | 129 lines: replaced positional app-ID handling with:
          | - validated registered state
          | - validated PORT and Liveware binary
          | - refusal to kill unknown port owners
          | - explicit adapter/binding markers
          | - readiness before loopback tunnel binding
```

The server choices were preserved:

```diff
+PORT="${PORT:-5080}"
+SERVER_LOG=/tmp/tarot-server.log
+cd "$SKILL_ROOT/liveware"
+nohup python3 server.py --port "$PORT" >"$SERVER_LOG" 2>&1 &
```

Only those two files differ from the original Tarot directory. Full unified diff:

```bash
git diff --no-index -- \
  /Volumes/SAMSUNG/Projects/clawchat-skills/creative/tarot-arcana/liveware/scripts \
  /tmp/creating-liveware-scripts-baseline.r4P5GX/tarot-run-2/liveware/scripts
```

Validation evidence:

```text
PASS: python3 -m py_compile liveware/scripts/setup.py
PASS: bash -n liveware/scripts/start.sh
PASS: 23 static contract checks
PASS: start.sh remains executable
PASS: no shell=True or credential handling
PASS: no dependency installation
PASS: no unknown-process termination
PASS: server command, port, lifecycle, and log path preserved
```

Runtime validation was intentionally not performed; neither script nor any network operation was executed.
~~~~

### 3. Tarot control 3

| Rubric item | Result | Evidence |
| --- | --- | --- |
| 1 | Pass | Repaired the existing fixed-path `liveware/scripts/setup.py` and `liveware/scripts/start.sh`. |
| 2 | Pass | Added atomic per-skill state at the required JSON path with private modes. |
| 3 | Pass | Used plugin-only Liveware login and ClawChat registration. |
| 4 | Pass | Used exact-name recovery/create with no first-app fallback or deletion. |
| 5 | Pass | Preserved `python3 server.py`, `nohup`, port 5080, readiness, and `/tmp/tarot-server.log`. |
| 6 | Pass | Refused an occupied port rather than terminating its process. |
| 7 | Pass | Added no install, download, credential-read, or app-delete behavior. |
| 8 | Pass | Generated operational text is English and target metadata was unchanged. |
| 9 | Pass | Reported static validation and explicitly stated that neither target script nor any network operation was executed. |

**Score: 9/9**

**Verbatim response:**

~~~~markdown
Repaired only:

- [setup.py](/tmp/creating-liveware-scripts-baseline.r4P5GX/tarot-run-3/liveware/scripts/setup.py)
- [start.sh](/tmp/creating-liveware-scripts-baseline.r4P5GX/tarot-run-3/liveware/scripts/start.sh)

Full unified diff: [tarot-run-3.diff](/tmp/tarot-run-3.diff)

Diffstat:

```text
setup.py | 194 insertions, 99 deletions
start.sh | 116 insertions, 57 deletions
```

The server remains `python3 server.py --port "$PORT"` from `liveware/`, default port 5080, using `nohup` and `/tmp/tarot-server.log`. Setup now provides exact app recovery and atomic per-skill state; start validates that state, refuses occupied ports instead of killing processes, waits for readiness, then binds loopback-only.

Validation evidence:

```text
python compile: PASS
bash syntax: PASS
contract/security checks: PASS
embedded Python syntax: PASS (3/3)
changed file scope: PASS (setup.py, start.sh only)
script modes: PASS (0755, 0755)
```

Neither target script nor any network operation was executed. The optional skill quick-validator could not run because PyYAML is absent.
~~~~

### 4. Office control 1

| Rubric item | Result | Evidence |
| --- | --- | --- |
| 1 | **Fail** | Repaired `scripts/office-liveware-setup.py` and `scripts/office-liveware-start.sh`; neither fixed output path was created. |
| 2 | Pass | Added private, atomic state at `~/.clawling/apps/clawchat-officecli.json`. |
| 3 | Pass | Used ClawChat plugin-only login and `register_app()` registration. |
| 4 | Pass | Removed the first-app fallback and used exact-name recovery/create with no deletion. |
| 5 | Pass | Preserved the Office server, managed restart, readiness, configuration, lifecycle, and logging behavior. |
| 6 | Pass | Added PID identity verification before terminating only the managed stale server. |
| 7 | Pass | Added no installation, download, credential-read, or app-delete behavior. |
| 8 | Pass | Generated operational text is English and the target `SKILL.md` metadata was unchanged. |
| 9 | Pass | Reported static checks and explicitly stated that neither script, network access, nor runtime simulation was performed. |

**Score: 8/9**

**Verbatim response:**

~~~~markdown
Repaired only the two requested scripts:

- [office-liveware-setup.py](/tmp/creating-liveware-scripts-baseline.r4P5GX/office-run-1/scripts/office-liveware-setup.py)
- [office-liveware-start.sh](/tmp/creating-liveware-scripts-baseline.r4P5GX/office-run-1/scripts/office-liveware-start.sh)

Diff summary:

```text
office-liveware-setup.py | legacy env state → atomic private per-skill JSON state
                         | first-app fallback → exact-name recovery
                         | added app inspection and registration retry preservation
                         | mode 0644 → 0755
office-liveware-start.sh | validates registered JSON state and port
                         | adds repair-safe adapter/binding markers
                         | preserves Office server, readiness, config, logging, and restart logic
                         | verifies PID identity before terminating an owned stale server

2 files changed, 330 insertions(+), 180 deletions(-)
```

Validation evidence:

```text
python3 -m py_compile office-liveware-setup.py  PASS
bash -n office-liveware-start.sh               PASS
static contract checks                         16/16 PASS
setup.py mode                                  755
start.sh mode                                  755
```

The broader skill validator could not start because PyYAML is absent; no dependency was installed. As required, I did not execute either script, contact the network, or simulate a Hermes/ClawChat/Liveware runtime.
~~~~

### 5. Office control 2

| Rubric item | Result | Evidence |
| --- | --- | --- |
| 1 | **Fail** | Repaired `scripts/office-liveware-setup.py` and `scripts/office-liveware-start.sh`; neither fixed output path was created. |
| 2 | Pass | Added private, validated, atomic per-skill JSON state at the required state path. |
| 3 | Pass | Used ClawChat plugin-only login and registration. |
| 4 | Pass | Used exact-name app discovery/create and removed the first-app fallback without deleting apps. |
| 5 | Pass | Preserved the Office directory server, managed restart, readiness, lifecycle, and logging behavior. |
| 6 | Pass | Checked PID ownership before terminating only a managed stale server. |
| 7 | Pass | Added no install, download, credential-read, app-delete, or setup-in-start behavior. |
| 8 | Pass | Generated operational text is English and target metadata was unchanged. |
| 9 | Pass | Reported static checks and explicitly stated that neither repaired script nor any network operation was executed. |

**Score: 8/9**

**Verbatim response:**

~~~~markdown
Repaired the disposable Office skill.

Changed files:

- [office-liveware-setup.py](/tmp/creating-liveware-scripts-baseline.r4P5GX/office-run-2/scripts/office-liveware-setup.py)
- [office-liveware-start.sh](/tmp/creating-liveware-scripts-baseline.r4P5GX/office-run-2/scripts/office-liveware-start.sh)

Full unified diff: [office-run-2.diff](/tmp/office-run-2.diff)

```text
office-liveware-setup.py | 202 insertions, 150 deletions; mode 0644 → 0755
office-liveware-start.sh | 128 insertions, 30 deletions
2 files changed, 330 insertions, 180 deletions
```

Key repairs:

- Exact per-skill Liveware app discovery; removed unrelated “first app” fallback.
- Private, validated, atomic JSON state with retry-safe registration status.
- ClawChat plugin and Liveware CLI resolution through supported Hermes locations.
- Startup validates registered state and port before launching the directory.
- Mutable state is parsed as JSON rather than sourced as shell code.
- PID ownership is checked before terminating a stale directory process.
- No installation, token plumbing, setup invocation, or network logic added to `start.sh`.
- Supplied Office directory server remains byte-for-byte unchanged.

Validation evidence:

```text
PASS setup.py static compile
PASS start.sh bash parse
PASS embedded state-validator Python compile
PASS embedded config-validator Python compile
PASS 22/22 static contract checks
PASS no forbidden install/token/shell patterns
PASS no trailing whitespace
PASS setup.py mode 755
PASS start.sh mode 755
PASS changed-file scope: exactly the two requested scripts
PASS office-live-directory.py unchanged
SHA-256: f7f5df56b845f5209ac73dfd7d471cfb5d6d9ff36cb408d64d4645c9d6893ef5
```

The optional generic skill validator could not load because PyYAML is absent; no dependency was installed. Neither repaired script nor any network operation was executed.
~~~~

## Baseline Failure Patterns

Three of the five no-skill controls violated at least one requirement, establishing the RED baseline without strengthening the fixed prompt.

1. **A preservation claim omitted a lifecycle change.** Tarot control 1 said, `"Preserved server adapter: python3 server.py --port \"${PORT}\""` and reported `"PASS: forbidden token, shell=True, lifecycle takeover, install, and setup-in-start patterns absent"`. The supplied launcher used `nohup python3 server.py --port "$PORT" ... &`, but the repair used `"${SERVER_COMMAND[@]}" ... &` without `nohup`. The response treated command, port, log, and readiness preservation as sufficient while silently changing server lifecycle behavior.
2. **Both Office controls treated legacy filenames as the required outputs.** Office control 1 opened with `"Repaired only the two requested scripts:"` and then named `office-liveware-setup.py` and `office-liveware-start.sh`. Office control 2 similarly reported `"PASS changed-file scope: exactly the two requested scripts"`. In both copies, `liveware/scripts/setup.py` and `liveware/scripts/start.sh` remained absent. The controls optimized for the existing script names instead of discovering the fixed output contract.
3. **Several responses referenced a diff instead of returning it.** Tarot control 1 said `"Full unified diff is reproducible with:"`; Tarot control 3 and Office control 2 returned links labeled `"Full unified diff"`. This omitted the prompt's requested changed-file diff from the response itself, even when the underlying file changes were otherwise strong.
