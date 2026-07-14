#!/usr/bin/env node

/**
 * draw-tarot.mjs — Secure tarot card draw script
 *
 * Reads deck.json from the assets/ directory (relative to this script),
 * shuffles using crypto.randomInt, draws cards without repetition,
 * assigns positions and random orientation, outputs structured JSON.
 *
 * Usage:
 *   node draw-tarot.mjs --spread one_card --question "My question"
 *   node draw-tarot.mjs --spread three_card --question "Work this week" --reversals true
 */

import { randomInt, randomUUID } from "crypto";
import { readFileSync, existsSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

// ── Path resolution ──────────────────────────────────────────────────────
const __dirname = dirname(fileURLToPath(import.meta.url));
const SKILL_ROOT = join(__dirname, "..");
const DECK_PATH = join(SKILL_ROOT, "assets", "deck.json");

// ── Argument parsing (strict) ────────────────────────────────────────────

function readOptionValue(args, index, name) {
  const value = args[index + 1];
  if (value === undefined || value === null || value.startsWith("--")) {
    console.error(`Error: --${name} requires a value.`);
    process.exit(1);
  }
  return value;
}

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { spread: null, question: "", reversals: true };

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--spread": {
        const val = readOptionValue(args, i, "spread");
        if (val !== "one_card" && val !== "three_card") {
          console.error(
            `Error: --spread must be "one_card" or "three_card", got "${val}".`
          );
          process.exit(1);
        }
        opts.spread = val;
        i++;
        break;
      }
      case "--question": {
        const val = readOptionValue(args, i, "question");
        if (val.trim().length === 0) {
          console.error("Error: --question must be a non-empty string.");
          process.exit(1);
        }
        opts.question = val;
        i++;
        break;
      }
      case "--reversals": {
        const val = readOptionValue(args, i, "reversals");
        opts.reversals = val === "true" || val === "1";
        i++;
        break;
      }
      default:
        console.error(`Error: Unknown argument: ${args[i]}`);
        process.exit(1);
    }
  }

  if (!opts.spread) {
    console.error('Error: --spread is required ("one_card" or "three_card").');
    process.exit(1);
  }

  if (!opts.question) {
    console.error("Error: --question is required.");
    process.exit(1);
  }

  return opts;
}

// ── Fisher-Yates shuffle (crypto-backed) ─────────────────────────────────
function shuffle(array) {
  const a = [...array];
  for (let i = a.length - 1; i > 0; i--) {
    const j = randomInt(0, i + 1);
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// ── Spread definitions ───────────────────────────────────────────────────
const SPREADS = {
  one_card: {
    count: 1,
    positions: [
      {
        position: "current_reminder",
        name: "Current Reminder",
        description:
          "The core message, current state, or immediate guidance for this question.",
      },
    ],
  },
  three_card: {
    count: 3,
    positions: [
      {
        position: "current_situation",
        name: "Current Situation",
        description:
          "Current situation, background, or what is happening right now.",
      },
      {
        position: "obstacle",
        name: "Obstacle",
        description:
          "Blockage, challenge, resistance, blind spot, or what stands in the way.",
      },
      {
        position: "advice",
        name: "Advice",
        description:
          "Guidance, recommended action, or what to focus on moving forward.",
      },
    ],
  },
};

// ── Deck validation ──────────────────────────────────────────────────────
function validateDeck(deck) {
  if (!Array.isArray(deck)) {
    console.error("Error: Deck is not an array.");
    process.exit(1);
  }

  if (deck.length !== 78) {
    console.error(
      `Error: Deck must have exactly 78 cards, but got ${deck.length}.`
    );
    process.exit(1);
  }

  const seenIds = new Set();
  const VALID_ARCANA = new Set(["major", "minor"]);

  for (let i = 0; i < deck.length; i++) {
    const card = deck[i];
    const idx = `card[${i}]`;

    if (!card.id || typeof card.id !== "string") {
      console.error(`Error: ${idx} is missing a string id.`);
      process.exit(1);
    }
    if (seenIds.has(card.id)) {
      console.error(`Error: Duplicate card id "${card.id}" at ${idx}.`);
      process.exit(1);
    }
    seenIds.add(card.id);

    if (!card.name || typeof card.name !== "string") {
      console.error(`Error: ${idx} (id="${card.id}") is missing name.`);
      process.exit(1);
    }

    if (!VALID_ARCANA.has(card.arcana)) {
      console.error(
        `Error: ${idx} (id="${card.id}") arcana must be "major" or "minor", got "${card.arcana}".`
      );
      process.exit(1);
    }

    for (const orient of ["upright", "reversed"]) {
      const data = card[orient];
      if (!data || typeof data !== "object") {
        console.error(
          `Error: ${idx} (id="${card.id}") is missing "${orient}" object.`
        );
        process.exit(1);
      }
      if (!Array.isArray(data.keywords)) {
        console.error(
          `Error: ${idx} (id="${card.id}") ${orient}.keywords must be an array.`
        );
        process.exit(1);
      }
      if (typeof data.summary !== "string") {
        console.error(
          `Error: ${idx} (id="${card.id}") ${orient}.summary must be a string.`
        );
        process.exit(1);
      }
    }
  }
}

// ── Main ─────────────────────────────────────────────────────────────────
function main() {
  const opts = parseArgs();

  // Load deck
  if (!existsSync(DECK_PATH)) {
    console.error(`Error: Deck file not found at ${DECK_PATH}`);
    process.exit(1);
  }

  let deck;
  try {
    const raw = readFileSync(DECK_PATH, "utf-8");
    deck = JSON.parse(raw);
  } catch (err) {
    console.error(`Error: Failed to read or parse deck file: ${err.message}`);
    process.exit(1);
  }

  validateDeck(deck);

  const spreadDef = SPREADS[opts.spread];

  // Shuffle and draw
  const shuffled = shuffle(deck);
  const drawn = shuffled.slice(0, spreadDef.count);

  // Build cards output
  const cards = drawn.map((card, index) => {
    const pos = spreadDef.positions[index];
    const isReversed = opts.reversals ? randomInt(0, 2) === 1 : false;
    const orientation = isReversed ? "reversed" : "upright";
    const cardData = isReversed ? card.reversed : card.upright;

    return {
      position: pos.position,
      positionName: pos.name,
      positionDescription: pos.description,
      cardId: card.id,
      name: card.name,
      arcana: card.arcana,
      suit: card.suit ?? null,
      number: card.number ?? null,
      orientation,
      keywords: cardData.keywords,
      summary: cardData.summary,
      summaryModern: cardData.summaryModern ?? null,
    };
  });

  const readingResult = {
    mode: "interpret_existing_tarot_reading",
    readingId: randomUUID(),
    spread: opts.spread,
    question: opts.question,
    reversalsEnabled: opts.reversals,
    cards,
    drawTimestamp: new Date().toISOString(),
  };

  console.log(JSON.stringify(readingResult, null, 2));
}

main();
