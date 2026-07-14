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
| Install liveware (first time) | `python3 scripts/liveware/setup.py && bash scripts/liveware/start.sh <app-id>` (from skill dir) |
| Activate liveware (daily) | `bash scripts/liveware/start.sh <app-id>` (from skill dir) |

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

See `references/liveware-app.md` for setup and activation instructions.

## Bundled Files

Hermes installation must include every runtime support file below:

- `assets/deck.json`
- `assets/liveware/assets/index-C9bqGTKi.css`
- `assets/liveware/assets/index-Dwj4Kkvv.js`
- `assets/liveware/cards/00-TheFool.jpg`
- `assets/liveware/cards/01-TheMagician.jpg`
- `assets/liveware/cards/02-TheHighPriestess.jpg`
- `assets/liveware/cards/03-TheEmpress.jpg`
- `assets/liveware/cards/04-TheEmperor.jpg`
- `assets/liveware/cards/05-TheHierophant.jpg`
- `assets/liveware/cards/06-TheLovers.jpg`
- `assets/liveware/cards/07-TheChariot.jpg`
- `assets/liveware/cards/08-Fortitude.jpg`
- `assets/liveware/cards/09-TheHermit.jpg`
- `assets/liveware/cards/10-WheelOfFortune.jpg`
- `assets/liveware/cards/11-Justice.jpg`
- `assets/liveware/cards/12-TheHangedMan.jpg`
- `assets/liveware/cards/13-Death.jpg`
- `assets/liveware/cards/14-Temperance.jpg`
- `assets/liveware/cards/15-TheDevil.jpg`
- `assets/liveware/cards/16-TheTower.jpg`
- `assets/liveware/cards/17-TheStar.jpg`
- `assets/liveware/cards/18-TheMoon.jpg`
- `assets/liveware/cards/19-TheSun.jpg`
- `assets/liveware/cards/20-TheLastJudgment.jpg`
- `assets/liveware/cards/21-TheWorld.jpg`
- `assets/liveware/cards/CardBacks.jpg`
- `assets/liveware/cards/Cups01.jpg`
- `assets/liveware/cards/Cups02.jpg`
- `assets/liveware/cards/Cups03.jpg`
- `assets/liveware/cards/Cups04.jpg`
- `assets/liveware/cards/Cups05.jpg`
- `assets/liveware/cards/Cups06.jpg`
- `assets/liveware/cards/Cups07.jpg`
- `assets/liveware/cards/Cups08.jpg`
- `assets/liveware/cards/Cups09.jpg`
- `assets/liveware/cards/Cups10.jpg`
- `assets/liveware/cards/Cups11.jpg`
- `assets/liveware/cards/Cups12.jpg`
- `assets/liveware/cards/Cups13.jpg`
- `assets/liveware/cards/Cups14.jpg`
- `assets/liveware/cards/Pentacles01.jpg`
- `assets/liveware/cards/Pentacles02.jpg`
- `assets/liveware/cards/Pentacles03.jpg`
- `assets/liveware/cards/Pentacles04.jpg`
- `assets/liveware/cards/Pentacles05.jpg`
- `assets/liveware/cards/Pentacles06.jpg`
- `assets/liveware/cards/Pentacles07.jpg`
- `assets/liveware/cards/Pentacles08.jpg`
- `assets/liveware/cards/Pentacles09.jpg`
- `assets/liveware/cards/Pentacles10.jpg`
- `assets/liveware/cards/Pentacles11.jpg`
- `assets/liveware/cards/Pentacles12.jpg`
- `assets/liveware/cards/Pentacles13.jpg`
- `assets/liveware/cards/Pentacles14.jpg`
- `assets/liveware/cards/Swords01.jpg`
- `assets/liveware/cards/Swords02.jpg`
- `assets/liveware/cards/Swords03.jpg`
- `assets/liveware/cards/Swords04.jpg`
- `assets/liveware/cards/Swords05.jpg`
- `assets/liveware/cards/Swords06.jpg`
- `assets/liveware/cards/Swords07.jpg`
- `assets/liveware/cards/Swords08.jpg`
- `assets/liveware/cards/Swords09.jpg`
- `assets/liveware/cards/Swords10.jpg`
- `assets/liveware/cards/Swords11.jpg`
- `assets/liveware/cards/Swords12.jpg`
- `assets/liveware/cards/Swords13.jpg`
- `assets/liveware/cards/Swords14.jpg`
- `assets/liveware/cards/Wands01.jpg`
- `assets/liveware/cards/Wands02.jpg`
- `assets/liveware/cards/Wands03.jpg`
- `assets/liveware/cards/Wands04.jpg`
- `assets/liveware/cards/Wands05.jpg`
- `assets/liveware/cards/Wands06.jpg`
- `assets/liveware/cards/Wands07.jpg`
- `assets/liveware/cards/Wands08.jpg`
- `assets/liveware/cards/Wands09.jpg`
- `assets/liveware/cards/Wands10.jpg`
- `assets/liveware/cards/Wands11.jpg`
- `assets/liveware/cards/Wands12.jpg`
- `assets/liveware/cards/Wands13.jpg`
- `assets/liveware/cards/Wands14.jpg`
- `assets/liveware/deck.json`
- `assets/liveware/favicon.svg`
- `assets/liveware/icons.svg`
- `assets/liveware/index.html`
- `references/interpretation-rules.md`
- `references/liveware-app.md`
- `references/question-framework.md`
- `references/spreads.md`
- `scripts/draw-tarot.mjs`
- `scripts/liveware/server.py`
- `scripts/liveware/setup.py`
- `scripts/liveware/start.sh`

## Post-reading follow-up

When the user follows up about a web reading, recover context from `~/tarot-readings/latest.json` or the indexed markdown files.

## Verification

- Draw command succeeds and returns valid JSON
- Cards match the selected spread count (1 or 3)
- No duplicate cards in one draw
- Interpretation follows the reference sequence and includes actionable advice
- Tone stays reflective, useful, and non-fear-based
