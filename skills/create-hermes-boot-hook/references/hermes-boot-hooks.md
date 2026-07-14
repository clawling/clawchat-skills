# Hermes BOOT hook reference

Use this reference to generate customized runtime files. It describes the verified design, not files to copy unchanged.

Primary lifecycle and manifest reference: [Hermes Agent — Event Hooks](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks).

## Runtime layout

```text
~/.hermes/
├── BOOT.md
└── hooks/
    └── boot-md/
        ├── HOOK.yaml
        └── handler.py
```

`BOOT.md`, `HOOK.yaml`, and `handler.py` are generated outputs. This skill intentionally has no generator script or assets directory because the agent must adapt them to the user's requirements and existing Hermes configuration.

## Lifecycle and ownership

`gateway:startup` is the correct Hook event for work that should begin whenever the Hermes Gateway starts or restarts. The startup hook is called before the initial channel-directory build. Its context provides the configured `platforms`; it does not provide a current inbound chat, a gateway runner, or a Session store.

Keep responsibilities separate:

1. `HOOK.yaml` subscribes the handler to `gateway:startup`.
2. `handle()` starts a daemon worker and returns so gateway startup is not blocked.
3. The worker loads `BOOT.md`, resolves the active gateway model and provider runtime, and runs one `AIAgent` conversation.
4. The agent performs the requested checks and returns a final report. It does not deliver the report.
5. The worker filters exact silence tokens and, when the user requested notification, delivers a non-silent report through the in-process `send_message_tool`.
6. `send_message_tool` performs platform delivery and attempts to mirror the outgoing assistant message into an existing matching Session.

This ownership prevents duplicate sends and keeps delivery status observable by the handler.

If the user requests Liveware lifecycle work on every gateway restart, execute the confirmed setup/start policy deterministically at the beginning of the same worker, before constructing the agent. Feed its concise success or failure status into the agent prompt when the BOOT report should mention it.

## BOOT.md contract

Write `BOOT.md` as a precise one-shot prompt. Include:

- the startup task and its scope;
- allowed tools and safety limits;
- the evidence the agent must gather;
- the final report's language, structure, and useful level of detail;
- exact conditions for silence;
- a final instruction to return only `[SILENT]` when there is nothing worth notifying;
- a prohibition against calling `send_message`, because the handler owns delivery.

Avoid vague instructions such as “check everything.” Define failures, warnings, freshness windows, and paths or services where relevant. The task must be safe to repeat after every gateway restart.

## HOOK.yaml contract

Generate the manifest using the schema supported by the installed Hermes version. A typical shape is:

```yaml
name: boot-md
description: Run the customized BOOT.md workflow after gateway startup
events:
  - gateway:startup
```

Hermes discovers the sibling file specifically as `handler.py`; there is no `handler:` field in the documented manifest. If an existing Hermes hook uses additional supported metadata, preserve it. Do not change the event to a session or message event as a workaround for delivery continuity; that changes the requested lifecycle.

## handler.py implementation pattern

Adapt the following mechanics to the installed Hermes version and the user's delivery requirements. Verify import paths against the runtime if they differ.

```python
import json
import logging
import threading
from pathlib import Path

from gateway.run import _resolve_gateway_model, _resolve_runtime_agent_kwargs
from run_agent import AIAgent
from tools.send_message_tool import send_message_tool

logger = logging.getLogger(__name__)

HERMES_HOME = Path.home() / ".hermes"
BOOT_FILE = HERMES_HOME / "BOOT.md"
DELIVERY_TARGET = "telegram"  # Replace with an explicit target or configured platform.
SILENCE_TOKENS = {"[SILENT]", "SILENT", "NO_REPLY", "NO REPLY"}


def handle(event_type, context):
    if event_type != "gateway:startup":
        return
    platforms = tuple((context or {}).get("platforms") or ())
    threading.Thread(
        target=_run_boot_workflow,
        args=(platforms,),
        name="hermes-boot-md",
        daemon=True,
    ).start()


def _run_boot_workflow(platforms):
    try:
        prompt = BOOT_FILE.read_text(encoding="utf-8").strip()
        if not prompt:
            logger.info("BOOT hook skipped: %s is empty", BOOT_FILE)
            return

        runtime = _resolve_runtime_agent_kwargs()
        model = _resolve_gateway_model()
        agent = AIAgent(
            model=model,
            **runtime,
            quiet_mode=True,
            platform="gateway",
            skip_context_files=True,
            skip_memory=True,
            max_iterations=20,
        )
        result = agent.run_conversation(prompt)
        report = ((result or {}).get("final_response") or "").strip()

        if not report:
            logger.warning("BOOT hook produced no final response")
            return
        if report in SILENCE_TOKENS:
            logger.info("BOOT hook completed silently")
            return

        raw = send_message_tool({
            "action": "send",
            "target": DELIVERY_TARGET,
            "message": report,
        })
        delivery = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(delivery, dict):
            logger.error("BOOT hook delivery returned an invalid result")
            return
        if delivery.get("error"):
            logger.error("BOOT hook delivery failed: %s", delivery["error"])
            return
        if delivery.get("success") is not True:
            logger.error("BOOT hook delivery did not confirm success")
            return
        logger.info(
            "BOOT hook delivery succeeded: mirrored=%s",
            delivery.get("mirrored", False),
        )
    except Exception:
        logger.exception("BOOT hook worker failed")
```

The generated handler should improve this baseline where the installed version requires cleanup of agent resources or exposes configuration for enabled toolsets, fallback models, iteration limits, or service tiers. Keep the core ownership model unchanged.

## User-confirmed Liveware lifecycle

Liveware setup/start is an optional deterministic handler action, not an agent task. Do not assume that the app is already prepared, and do not assume that setup is allowed. Inspect the target skill first, then resolve the policy with the user one decision at a time.

### Facts to establish

- exact paths and interfaces of `liveware/scripts/setup.py` and `start.sh`;
- how local state represents an existing, registered app;
- whether setup recovers an exact-name remote app before creating one;
- setup's external effects: plugin login, app recovery/creation, state persistence, and ClawChat registration;
- start's server lifecycle, readiness behavior, tunnel binding, exit status, idempotency, and logging;
- whether ClawChat activation and the Liveware CLI are available at startup.

Missing local state does not prove that no remote app exists. When setup is permitted, rely on an inspected idempotent `setup.py` that recovers an exact matching app before creating one; do not implement app lookup or creation in the Hook.

### Decisions to confirm

Ask only applicable questions, one at a time:

1. Should this Liveware target be started on every gateway restart?
2. If its required state is missing, invalid, incomplete, or remotely stale, should the Hook fail and report, run setup if needed, or follow another policy?
3. If setup is allowed, what evidence triggers it? Recommend a structured state/readiness predicate from the target skill rather than parsing human-readable stderr.
4. May setup perform its known external changes without another prompt on each boot?
5. Should a non-setup start failure ever trigger setup and one retry? Recommend no unless the failure is explicitly classified as setup-recoverable.
6. What timeout, retry cap, and failure-notification behavior apply?

Recommend `setup-if-needed` only when the user wants self-healing and the inspected setup is exact-match, idempotent, and credential-safe. Otherwise recommend `require-prepared`, which fails with an actionable report. Permit `setup-on-every-boot` only after the user accepts repeated authentication/control-plane work.

### Generate the selected branch

Use one bounded subprocess helper for both scripts:

```python
import os
import subprocess

from agent.redact import redact_sensitive_text

LIVEWARE_SETUP = Path("/absolute/path/to/skill/liveware/scripts/setup.py")
LIVEWARE_START = Path("/absolute/path/to/skill/liveware/scripts/start.sh")
LIVEWARE_TIMEOUT_SECONDS = 60


def _run_liveware_step(argv: list[str], cwd: Path, label: str) -> dict:
    env = os.environ.copy()
    env.setdefault("HERMES_HOME", str(HERMES_HOME))
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=LIVEWARE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"{label} timed out"}
    except OSError as exc:
        return {
            "ok": False,
            "detail": redact_sensitive_text(f"{label} failed: {exc}"),
        }

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        return {"ok": False, "detail": redact_sensitive_text(detail[-500:])}
    detail = (completed.stdout or f"{label} succeeded").strip()
    return {"ok": True, "detail": redact_sensitive_text(detail[-500:])}
```

Generate an `_ensure_liveware()` orchestration function from the confirmed policy. For example, `setup-if-needed` evaluates the inspected structured predicate, runs `[python_executable, str(LIVEWARE_SETUP)]` at most once when needed, then runs `["bash", str(LIVEWARE_START)]` at most once. Add a single start retry only if the user explicitly approved it and the failure is reliably classified as setup-recoverable. Never use unbounded loops.

Call orchestration from `_run_boot_workflow()` before `AIAgent`. Keep it inside the daemon worker so gateway startup returns immediately. Use `subprocess.run()` rather than a blind `Popen()` for standard one-shot setup/start scripts: those scripts own their external effects, server lifecycle, and tunnel binding, while the Hook owns only the bounded orchestration attempt.

Do not reproduce Liveware login, token handling, app lookup/creation, ClawChat registration, server launch, or tunnel binding in the Hook. Invoke the inspected scripts. If the user approves setup during startup, record that policy explicitly in generated code and explain that activation or credential unavailability can make it fail before platform connections are ready.

Do not assume every launcher is idempotent. A launcher that always starts a duplicate server, kills the process occupying its port, or fails whenever a healthy service survived the gateway restart is not boot-safe. Surface this fact during the interview and resolve it before generation.

For a BOOT report, append only a bounded, credential-free status block to the prompt; never inject raw environment variables or unlimited process output. If Liveware failure must always notify the user, state that explicitly in `BOOT.md`. If Liveware succeeds and nothing else needs attention, the agent may still return `[SILENT]`.

### Target selection

When the user requested notification, prefer a fully explicit target such as `telegram:-1001234567890` when the user supplies it. A bare platform such as `telegram` is valid only when that platform's home channel is configured. Do not depend on name resolution during startup because `gateway:startup` occurs before the first channel-directory build.

If more than one platform is configured, do not guess which one should receive the report. `context["platforms"]` may be used to log or validate availability, but it is not a destination by itself.

### Silence handling

Normalize only surrounding whitespace with `.strip()`. Compare the entire response exactly against:

```text
[SILENT]
SILENT
NO_REPLY
NO REPLY
```

Do not use substring matching. A genuine report that mentions “NO_REPLY” must still be delivered.

### Delivery result

`send_message_tool` returns a JSON string in the verified Hermes runtime, though defensive code may also accept a dictionary. Treat an `error` field as failure and require `success: true` before logging success. Log the returned `mirrored` value separately from delivery success: a message can be delivered successfully while `mirrored` is false.

Never log tokens, full provider configuration, raw credentials, or unredacted exception payloads from external services.

## Session continuity boundary

`send_message_tool` calls `mirror_to_session()` after successful delivery. `mirror_to_session()` looks up a matching Session by platform and destination origin and appends the assistant message when one already exists. It returns false when no matching Session exists; it deliberately does not create one.

Consequences:

- Existing destination Session: delivery can be mirrored, so a later user reply continues with the proactive message in context.
- No destination Session yet: delivery can still succeed, but mirroring is false. The hook cannot guarantee that the user's first later reply will contain the proactive message in its Session history.

Do not solve this by reaching into private gateway state, editing `sessions.json`, writing directly to Hermes SQLite, or modifying mirror semantics. Those approaches bypass Hermes Session ownership and are version-fragile. If guaranteed first-contact continuity is a requirement, report it as a separate product/integration requirement that needs a supported public Session-creation API or an inbound activation flow.

This boundary does not prevent `BOOT.md` or the handler from running before first activation. It only limits conversational history continuity for a proactively delivered message.

## Validation checklist

- The handler event is exactly `gateway:startup`.
- `handle()` returns promptly and worker exceptions cannot crash gateway startup.
- The worker uses `_resolve_gateway_model()` and `_resolve_runtime_agent_kwargs()`.
- The agent returns a report but does not send it.
- Delivery calls `send_message_tool` directly, not `subprocess` or `hermes send`.
- Optional Liveware orchestration matches the confirmed setup/start policy, invokes only inspected scripts with fixed argv and bounded execution, and performs no unapproved external changes.
- Silence uses whole-response exact matching.
- The target is explicit or backed by a configured home channel.
- Delivery failure and `mirrored` state are logged distinctly.
- No private `_gateway_runner_ref`, injected `session_store`, or Session-file mutation appears.
- All startup work is idempotent and safe on repeated restarts.
