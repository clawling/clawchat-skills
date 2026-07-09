---
name: tarot-arcana
display_name: Tarot Arcana
description: Tarot card drawing and interpretation — draws real cards via a local script, never fabricates results. Supports one-card and three-card spreads with structured psychological analysis.
category: creative
version: 0.23.0
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
| Install liveware (first time) | `bash liveware/scripts/setup.sh` (from skill dir) |
| Activate liveware (daily) | `bash liveware/scripts/start.sh` (from skill dir) |

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

### First-time setup

```bash
cd <skill-dir>
bash liveware/scripts/setup.sh
```

After setup, register the app to ClawChat with `clawchat_register_app`.

### Daily activation

```bash
cd <skill-dir>
bash liveware/scripts/start.sh
```

### API endpoints

- `POST /api/interpret` — submits card/question data to the Hermes API Server for interpretation. The API-server agent uses this skill to analyze and return the reading.
- `GET /api/deck` — serves 78-card deck data for the frontend.

Readings are saved to `~/tarot-readings/` with an `index.json` history and individual markdown files.

### Question guidance (frontend copy principles)

| Layer | Role |
|-------|------|
| Steps | Tell the user what to do at each stage |
| Placeholder | A real, relatable example question |
| Hint | Explains the structure of a good question |

No negative framing — tell the user what TO do, not what NOT to do.

## Post-reading follow-up

When the user follows up about a web reading, recover context from `~/tarot-readings/latest.json` or the indexed markdown files.

## Verification

- Draw command succeeds and returns valid JSON
- Cards match the selected spread count (1 or 3)
- No duplicate cards in one draw
- Interpretation follows the reference sequence and includes actionable advice
- Tone stays reflective, useful, and non-fear-based
