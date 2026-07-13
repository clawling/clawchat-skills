---
name: tarot-arcana
display_name: Tarot Arcana
description: Tarot card drawing and interpretation — draws real cards via a local script, never fabricates results. Supports one-card and three-card spreads with structured psychological analysis.
category: creative
version: 0.23.1
metadata:
  hermes:
    tags: [Creative, Tarot, Reflection, Liveware]
    related_skills: [liveware-app]
---

# Tarot Arcana

A tarot reading skill that draws real cards and interprets them with grounded psychological analysis. The interpretation belongs to the agent using this skill — the liveware web app is an optional interface for collecting questions and displaying results, but does not replace the agent's judgment.

## When to Use

Use this skill when the user wants to:

- Draw tarot cards for a reflective reading
- Interpret a one-card or three-card spread
- Explore a situation through psychological, non-prophetic tarot framing
- Follow up on a reading produced by the liveware web app

Do not present tarot as proof, diagnosis, professional advice, or guaranteed prediction. For high-stakes or third-party questions, answer in a reflective way that focuses on the user's choices, feelings, preparation, and boundaries.

## Quick Reference

| Task | Command or file |
|------|-----------------|
| Draw one card | `node scripts/draw-tarot.mjs --spread one_card --question "<question>"` |
| Draw three cards | `node scripts/draw-tarot.mjs --spread three_card --question "<question>"` |
| Disable reversals | Add `--reversals false` |
| Interpretation rules | `skill_view(name='tarot-arcana', file_path='references/interpretation-rules.md')` |
| Spread rules | `skill_view(name='tarot-arcana', file_path='references/spreads.md')` |
| Question templates | `skill_view(name='tarot-arcana', file_path='references/question-framework.md')` |
| Install liveware (first time) | `python3 liveware/scripts/setup.py && bash liveware/scripts/start.sh <app-id>` (from skill dir) |
| Activate liveware (daily) | `bash liveware/scripts/start.sh <app-id>` (from skill dir) |
| Liveware app reference | `skill_view(name='tarot-arcana', file_path='references/liveware-app.md')` |
| Registration auth chain | `skill_view(name='tarot-arcana', file_path='references/clawchat-registration-auth.md')` |

Run commands from the skill directory so relative paths resolve. The draw script requires `node` in PATH (Node.js built-ins only, no npm packages).

## Procedure

### 0. Guide the user to formulate a good question

When someone asks for a tarot reading, guide them through a structured question loop before drawing cards. Ask one at a time:

1. **Theme** — What area of life? Relationships, career, or something else?
2. **Situation** — What's the current situation? Give a bit of background.
3. **Core confusion** — What are you truly stuck on? Where's the block?
4. **Timeframe** — What time period are you looking at? A week, a month, three months?
5. **Focus** — What do you want the cards to help you see? Current state, obstacles, trends, choices, or next steps?

After the question is clear, generate the liveware URL with the question pre-filled:

```
https://<app-id>.apps.clawling.io/?question=<url-encoded-question>
```

If liveware is unavailable, proceed with Step 1 and draw cards in chat directly.

### 1. Choose the reading mode

- **one_card** — focused reminder, immediate theme, or simple reflective prompt.
- **three_card** — fuller situation arc: current situation → obstacle → advice.

### 2. Load the reference files

Before interpreting, load:
- `references/interpretation-rules.md` — interpretation sequence, reading-depth rules, golden rules, safety boundaries
- `references/spreads.md` — spread types, position meanings

### 3. Draw real cards

```bash
# One card
node scripts/draw-tarot.mjs --spread one_card --question "<question>"

# Three cards
node scripts/draw-tarot.mjs --spread three_card --question "<question>"
```

The script returns structured JSON with cards, positions, orientations, and keywords. Never invent cards, positions, or orientations.

### 4. Interpret in order

1. **User's question** — identify what they're actually asking
2. **Spread type** — one_card or three_card
3. **Position meaning** — position takes priority over general card meaning
4. **Card name** — identify and note major/minor arcana
5. **Orientation** — upright/reversed modifies the energy
6. **Keywords** — use as shorthand anchors
7. **Summary** — apply the card meaning in context
8. **Situation reading** — identify patterns, blind spots, or relationship structures
9. **Synthesis** — connect all cards into one coherent narrative
10. **Actionable advice** — translate insight into grounded next steps

### 5. Keep readings reflective

- Answer the user's real concern whenever possible
- Do not present tarot as proof, diagnosis, professional instruction, or guaranteed outcome
- For high-stakes or third-party questions, focus on the user's feelings, options, and boundaries
- Avoid fear, shame, and manufactured urgency

## Liveware Web App

The liveware web app is an optional browser interface. It does not replace the agent's interpretation.

### First-time setup (setup.py)

`setup.py` handles all three registration steps — login, app creation, and ClawChat registration:

```bash
cd <skill-dir>
python3 liveware/scripts/setup.py
```

The script:
1. Calls `tools.liveware_login()` via the ClawChat plugin (no manual token handling)
2. Runs `liveware app list` first to check for an existing app, then `liveware app create` if needed
3. Calls `tools.register_app()` to register with ClawChat (URL constructed from app ID)

On success it prints `APP_ID=<id>` — pass this to start.sh.

### Daily activation (start.sh)

After setup, or when tarot is already registered, start the server and bind the tunnel:

```bash
cd <skill-dir>
bash liveware/scripts/start.sh <app-id>
```

The app ID is required. When called from the boot handler (`handler.py`'s `_start_tarot_liveware`), it passes the app ID as the first argument automatically.

### Responsibilities

| Script | Steps |
|--------|-------|
| `setup.py` | login → create app → register to ClawChat |
| `start.sh` | start server → bind tunnel |

### Pitfalls

- **setup.py needs the ClawChat plugin path** — it adds `$HERMES_HOME/../plugins/clawchat` to sys.path to import `clawchat_gateway.tools`. If the plugin is installed elsewhere, the import will fail.
- **start.sh requires app ID** — always pass it as the first argument. The old fallback to `~/.clawling/tarot-app-id` is a legacy path and may not exist.
- **setup.sh is deprecated** — the old `setup.sh` has been replaced by `setup.py`. Do not use it. It manually read CLAWCHAT_TOKEN from `.env` and did not actually register with ClawChat.
- **English-only user-facing text in published scripts** — This skill is published to a public repo (`clawling/clawchat-skills`). All user-facing text (docstrings, `print()` output, comments, error messages) in scripts under `liveware/` must be in English. Chinese or other localized text will be flagged by the skill maintainer. Setup scripts in particular are shared artifacts — keep them language-agnostic.
- **GitHub published version may not have setup.py** — The published repo (`clawling/clawchat-skills`) under `creative/tarot-arcana/liveware/scripts/` only has `setup.sh` and `start.sh`; `setup.py` may not be pushed yet. If you're setting up from a GitHub clone and `setup.py` doesn't exist, either create it (see the local skill dir for the authoritative version) or fall back to the deprecated `setup.sh`. Always verify the published repo's contents before referencing `setup.py` for a fresh install.

### API endpoints

See `skill_view(name='tarot-arcana', file_path='references/liveware-app.md')` for API endpoint details and readings storage.

## Post-reading follow-up

When the user follows up about a web reading, recover context from `~/tarot-readings/latest.json` or the indexed markdown files.

## Verification

- Draw command succeeds and returns valid JSON
- Cards match the selected spread count (1 or 3)
- No duplicate cards in one draw
- Interpretation follows the reference sequence and includes actionable advice
- Tone stays reflective, useful, and non-fear-based
