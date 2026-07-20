---
name: create-hermes-boot-hook
description: Design, create, audit, or update a Hermes Agent gateway:startup Hook and, when needed, its BOOT.md agent checklist. Use when a user wants a one-shot startup checklist, deterministic boot actions such as Liveware setup or start, Session-aware delivery to any configured chat platform, or repair of the active profile's boot-md Hook.
---

# Create Hermes BOOT Hook

Build the smallest safe startup workflow that satisfies the user's request. Do not force an agent turn, Liveware lifecycle action, or notification into every Hook.

## Read the reference

Read [references/hermes-boot-hooks.md](references/hermes-boot-hooks.md) completely before inspecting or changing Hermes runtime files. Recheck installed Hermes interfaces when the reference says they are version-sensitive.

## Choose the execution mode

Classify the requested outcome before discussing implementation:

- **Agent checklist**: use `BOOT.md` when startup work requires tools, interpretation, summarization, or a conditional report.
- **Deterministic Hook**: use `handler.py` without an agent when startup work is a known command, service action, health check, or fixed notification.
- **Hybrid**: run bounded deterministic actions first, then pass only their redacted status to one agent turn.

Recommend the deterministic mode for work that does not need model judgment. Create `BOOT.md` only for the agent and hybrid modes.

Treat Audit as read-only. Inspect and validate the selected mode, report findings, and do not enter the implementation phase unless the user asks for changes.

## Discover before asking

Inspect read-only facts first:

- the effective Hermes home and active profile; use Hermes' installed home resolver when available instead of assuming `~/.hermes`;
- the installed Hermes version, official Hook schema, runtime imports, and handler signature;
- existing `BOOT.md`, `hooks/boot-md/HOOK.yaml`, and `hooks/boot-md/handler.py`;
- the exact task inputs, commands, paths, readiness signals, ownership, and repeatability;
- for Liveware, the target skill and its actual `setup.py`, `start.sh`, state contract, service lifecycle, readiness check, timeout behavior, and logs;
- enabled gateway platforms, their configured Home or platform-owned activation bindings, existing Hermes Sessions, and any live Gateway Session capability only when delivery is requested; inspect the emitted startup context and installed binding types instead of assuming those interfaces.

Do not run setup, login, registration, service start, gateway restart, or external delivery during discovery.

## Resolve the startup contract

Ask only questions whose answers materially change the generated files. Ask one question per message, include the relevant discovered facts, and recommend an answer with a short reason.

Resolve applicable decisions in this order:

1. Desired startup outcome and execution mode.
2. Exact deterministic actions, ordering, readiness, timeout, idempotency, and failure behavior.
3. Agent task, allowed tools, evidence, iteration limit, report shape, and exact silence token.
4. Liveware policy: require prepared state, setup if a verified predicate fails, or setup on every boot; include external effects and retry cap.
5. Output policy: log only, no output, or deliver through one authoritative platform binding after it resolves to or safely creates one exact Session.
6. Static verification and any separately approved live test.

Do not repeat questions already answered by the request or environment. When an interview was necessary, restate the resolved contract before writing. A direct request to create or update files is sufficient authorization to write the confirmed design; it is not authorization to execute its startup actions.

## Implement the confirmed design

Preserve unrelated customizations and keep policy separate from mechanics.

- For Create or Update, always create or update `hooks/boot-md/HOOK.yaml` and its sibling `handler.py`.
- Add or update `BOOT.md` only when an agent turn is part of the design.
- Subscribe only to `gateway:startup`.
- Resolve the active Hermes home with the installed Hermes helper and propagate it to child processes.
- Make `handle(event_type, context)` return promptly; place all meaningful work in one guarded daemon worker.
- Use fixed argument arrays, `shell=False`, bounded timeouts and retries, bounded redacted output, and explicit success/failure results.
- Keep deterministic actions in the handler. Let the agent reason and produce a report; do not let it start Liveware or send the report.
- Invoke only inspected Liveware scripts. Do not copy their login, app, tunnel, server, or readiness logic into the Hook.
- Keep `BOOT.md` platform-neutral unless the startup task itself is platform-specific. Put platform and Session routing only in the handler.
- Add delivery only when requested. Treat startup `context["platforms"]` as availability information, not a destination, and do not assume a live `session_store` or narrower Session resolver is injected.
- In the inspected Hermes `v2026.7.7.2` runtime, startup provides platform names only (`{"platforms": ["clawchat", ...]}`). Do not call methods on those strings or invent a chat target.
- For ClawChat, read activation conversation and owner from the installed store. With `session_store`, build `SessionSource`, reuse/create the exact Session, and require mirror confirmation. Without it, use the installed target parser for transport-only delivery; do not claim Session continuity. Keep targets in memory only.
- For a Hybrid greeting, read `BOOT.md`, invoke one bounded `AIAgent` turn with tools disabled, use only its non-empty final response as the message, then perform routing and delivery in the handler. The Agent must never select a platform or call delivery tools.
- Write a bounded audit record for `hook_triggered`, `agent_start`, `agent_done` (response length only), `route_resolved`, transport result, mirror result, and full redacted exception details. This audit is diagnostic state, not user-facing content.
- Require a selected platform and one authoritative binding: its configured Home or a platform-owned activation binding. Never ask the user for raw routing coordinates or persist them in generated files.
- Treat each binding as a version-sensitive object. Resolve its complete origin and thread metadata internally; never stringify the whole object or log those fields.
- Reuse the exact existing Session when one matches. When none matches, permit the live Gateway-owned Session capability to get or create one only from the complete authoritative source and retain the returned Session as the delivery contract.
- Do not choose the most recently updated Session, construct another Session store, guess missing source fields, or fall back to another platform. A Home on another platform is irrelevant. Fail closed when activation is missing/incomplete; if Session capability is absent, report activation-only continuity as unverified.
- When an agent report exists only to be delivered, finish the routing preflight before invoking the model. Distinguish transport success from successful mirroring into the retained resolved-or-created Session.
- After confirmed mirroring, document that the next inbound message with the same full origin reuses that active Session unless Hermes applies an explicit or policy reset.
- Never mutate Hermes Session files or databases directly and never reach through private gateway-runner state to manufacture continuity.

## Validate without triggering startup effects

Perform every applicable static check:

1. Parse `HOOK.yaml`; require exactly `gateway:startup` and a sibling `handler.py`.
2. Compile `handler.py` without leaving bytecode in the runtime directory.
3. Import it with external actions stubbed and confirm `handle()` returns promptly and suppresses duplicate workers.
4. Confirm the active-home resolver, runtime model resolution, iteration bound, timeout/retry bounds, and whole-response silence comparison.
5. Confirm each deterministic branch matches the resolved policy and cannot loop indefinitely.
6. Confirm delivery cannot run without an authoritative binding and one exact resolved or safely created Session, extracts the installed binding object's fields instead of stringifying it, uses only the live Gateway-owned Session capability for creation, contains no embedded routing coordinates, parses the installed interface's result, and logs delivery and mirroring separately.
7. Scan for placeholders, TODOs, secrets, embedded destinations, recency-based Session selection, secondary Session stores, guessed Session sources, unbounded output, `shell=True`, hard-coded default-home paths, private gateway globals, and direct Session mutation.

Treat setup, start, login, registration, gateway restart, and real delivery as live tests. Run each only with separate explicit approval. For a reuse E2E, establish the intended Session with one normal inbound message before installing the Hook. For a creation E2E, establish only the authoritative platform binding and confirm that no matching Session exists. In either case, verify the visible message, exactly one resolved or created Session, its mirror in that Session, and a later reply reusing it. Report the selected mode, changed files, static evidence, unperformed live tests, and any delivery-continuity limitation.
