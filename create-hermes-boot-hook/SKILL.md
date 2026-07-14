---
name: create-hermes-boot-hook
description: Create or update customized Hermes Agent BOOT.md startup checklists and gateway:startup hooks, including HOOK.yaml and handler.py, through a one-question-at-a-time requirements interview. Supports user-chosen Liveware setup/start policies, one-shot agent execution, optional deterministic delivery, silence handling, validation, and Session-mirroring boundaries. Use when a user wants Liveware activation, checks, reports, alerts, maintenance, or other work whenever the Hermes Gateway starts or restarts.
---

# Create Hermes BOOT Hook

Create a Hermes startup workflow from the user's confirmed requirements. Never install a generic template or impose a fixed Liveware lifecycle policy.

## Required reference

Read [references/hermes-boot-hooks.md](references/hermes-boot-hooks.md) completely before inspecting or changing runtime files. Follow its Hermes architecture and decision boundaries.

## Discover facts first

Inspect facts instead of asking the user to supply them:

- the Hermes home, configuration, enabled platforms, and configured home channels;
- existing `BOOT.md`, `hooks/boot-md/HOOK.yaml`, and `hooks/boot-md/handler.py`;
- requested Liveware target skills, their `SKILL.md`, `liveware/scripts/setup.py`, `start.sh`, state contract, local service lifecycle, readiness check, and logging;
- Liveware CLI availability, local state, and read-only app/service status where safe;
- supported Hermes imports and Hook schema in the installed version.

Do not perform setup, login, app creation, registration, process startup, gateway restart, or external delivery during discovery.

## Interview decisions one at a time

Interview the user until both sides share an explicit startup contract. Walk the decision tree in dependency order. Ask exactly one question per message and wait for the answer. For every question, state the relevant discovered facts and give a recommended answer with a brief reason. Do not ask for a fact that the environment can establish.

Resolve only applicable branches:

1. Exact startup outcomes: agent work, Liveware targets, or both.
2. For each Liveware target, behavior when it is not prepared: fail and report, run existing `setup.py` if needed, run setup on every boot, or another user-specified policy.
3. If setup may run, the precise trigger, permission for its external changes, bounded retry policy, and behavior when ClawChat activation or credentials are unavailable.
4. Start ordering, readiness, timeout, idempotency, and failure behavior.
5. BOOT agent task, evidence, tools, limits, report format, and silence conditions.
6. Notification policy: no delivery, explicit `platform:target`, or a configured platform home channel; plus the accepted Session-continuity limitation.

When all branches are resolved, summarize the complete contract and ask one final question: whether shared understanding has been reached and file generation may begin. Do not create or modify runtime files before the user explicitly confirms.

## Generate the confirmed design

1. Preserve unrelated behavior and existing user customizations.
2. Generate or update exactly these runtime artifacts unless the user explicitly requests more:
   - `BOOT.md`: the customized one-shot agent checklist and report contract;
   - `hooks/boot-md/HOOK.yaml`: the `gateway:startup` manifest;
   - `hooks/boot-md/handler.py`: non-blocking deterministic orchestration, optional Liveware lifecycle actions, agent execution, silence filtering, delivery, and logging.
3. Keep user policy in clearly named handler configuration and `BOOT.md`; keep Hermes execution mechanics stable.
4. For Liveware, call only the inspected target skill's existing `setup.py` and `start.sh` according to the confirmed policy. Do not reproduce their login, app, tunnel, or server logic in the Hook.
5. Use fixed argument arrays without `shell=True`, bounded timeouts and retries, credential-redacted bounded output, and explicit success/failure handling.
6. Let the handler own deterministic Liveware actions and final delivery. The one-shot agent performs reasoning/checks and returns a report; it must not start Liveware or send the report itself.

## Validate

- Parse `HOOK.yaml` and confirm its event is exactly `gateway:startup` with a sibling `handler.py`.
- Compile `handler.py` with `python3 -m py_compile`.
- Confirm `handle(event_type, context)` returns promptly by starting a daemon worker.
- Confirm `_resolve_gateway_model()`, `_resolve_runtime_agent_kwargs()`, bounded agent execution, and exact whole-response silence tokens.
- Confirm generated Liveware branches exactly match the confirmed setup/start/retry policy and cannot loop without bounds.
- Confirm any delivery uses in-process `send_message_tool`, parses its JSON result, and logs delivery and `mirrored` separately.
- Scan for TODOs, example identifiers, placeholder targets, embedded secrets, `shell=True`, private gateway globals, and Session-store mutation.

Explain the resulting behavior and Session limitation. Do not execute generated setup/start actions, restart the gateway, or send a real external message without separate user approval.

## Fixed Hermes boundaries

- `gateway:startup` supplies `platforms`; it does not inject a current chat, gateway runner, or Session store.
- Use a daemon background worker so startup is never blocked by Liveware, an agent turn, or delivery.
- Never use `_gateway_runner_ref`, edit `sessions.json` or SQLite, or change `mirror_to_session()` to create sessions.
- Mirroring works only when the destination Session already exists. A startup Hook can run before first activation but cannot guarantee first-contact conversational continuity.
- Keep this skill to `SKILL.md`, `agents/openai.yaml`, and its reference; do not add copied runtime templates, scripts, or assets.
