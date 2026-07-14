---
name: creating-liveware-scripts
description: Use when creating, auditing, or repairing ClawChat Liveware setup.py and start.sh files for a Hermes skill.
---

# Create Liveware Scripts

## Principle

Preserve the supplied command, service manager, lifecycle, readiness, and logging behavior. Do not prescribe Python, Node, a script, or a service shape.

## Workflow

1. Require target `SKILL.md`. Output only `liveware/scripts/setup.py` and `liveware/scripts/start.sh`. Read `references/liveware-script-contract.md` completely.
2. Resolve the absolute directory containing this `SKILL.md` as `SKILL_DIR`. Capture analyzer stdout outside target, then inspect every evidence path and reason:

```bash
TARGET=/absolute/path/to/hermes-skill
SKILL_DIR=/absolute/path/to/creating-liveware-scripts
ANALYSIS_DIR="$(mktemp -d /tmp/creating-liveware-scripts.XXXXXX)"
ANALYSIS_JSON="$ANALYSIS_DIR/analysis.json"
python3 -B "$SKILL_DIR/scripts/analyze_target.py" "$TARGET" >"$ANALYSIS_JSON" || test "$?" -eq 2
```

Generate and Repair require ready analysis; never write provisional output when non-ready. On `ambiguous` or `blocked`, ask one question. Do not guess an entrypoint, port, lifecycle owner, readiness check, or log path.

Preserve exact argv, including lifecycle wrappers like `nohup`, only after evidence is inspected and coherent. Treat a composite Liveware launcher as unconfirmed; ask one narrow server-only question.

3. Audit continues when analysis is not ready. Audit a non-ready target without `--analysis`: run the validator without `--analysis` and report both analyzer issues and validator findings. Audit is read-only. Do not run `py_compile` in Audit mode:

```bash
python3 -B "$SKILL_DIR/scripts/validate_scripts.py" "$TARGET"
```

4. For Generate or apply, or Repair, preview before writing:

```bash
python3 -B "$SKILL_DIR/scripts/render_scripts.py" "$TARGET" "$ANALYSIS_JSON"
python3 -B "$SKILL_DIR/scripts/render_scripts.py" "$TARGET" "$ANALYSIS_JSON" --apply
python3 -B "$SKILL_DIR/scripts/render_scripts.py" "$TARGET" "$ANALYSIS_JSON" --replace-legacy
python3 -B "$SKILL_DIR/scripts/render_scripts.py" "$TARGET" "$ANALYSIS_JSON" --replace-legacy --apply
python3 -B "$SKILL_DIR/scripts/validate_scripts.py" "$TARGET" --analysis "$ANALYSIS_JSON"
PYTHONPYCACHEPREFIX="$ANALYSIS_DIR/pycache" python3 -B -m py_compile "$TARGET/liveware/scripts/setup.py"
bash -n "$TARGET/liveware/scripts/start.sh"
```

## Quick Reference

| Mode | Stop condition |
| --- | --- |
| Analyze | Generate/Repair only: status is not `ready` |
| Audit | Never stops before read-only validation |
| Generate/Repair | Evidence or canonical proof conflicts |
| Runtime | Real environment or authorization is missing |

## Example

For an externally managed Node service on `4173`, use `external`, target-owned logging, and readiness `http://127.0.0.1:{port}/healthz`; launch nothing.

## Repair Rules

- Require matching current setup/start manifests and a scaffold byte-canonical outside the binding block.
- Rebuild `liveware/scripts/setup.py`; replace only approved binding content in `liveware/scripts/start.sh`.
- For Repair, run the renderer without `--apply` for a repair preview, then rerun the renderer with `--apply`.
- For legacy migration, preview, then use explicit `--replace-legacy`; add `--apply` only after approval.
- Stop when manifests or markers are missing, invalid, or mismatched. If repair proof fails, show the read-only canonical diff and do not write.

## Safety Boundary

Do not install, download, delete apps, kill unknown processes, read credentials, or use `shell=True`. Reject path escapes. Automatic Python and Node candidates are evidence only. Do not run generated setup.py or start.sh without a real user-provided environment and authorization. Never claim fake runtime success. Report that runtime validation was not performed.

## Red Flags

- "The service already exists" is not permission to guess its port or lifecycle.
- "Just verify it" is not permission to run fixtures or generated scripts.

## Common Mistakes

- Treating examples as required server shapes; trusting noncanonical markers; replacing confirmed lifecycle/logging.
