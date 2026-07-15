---
name: personal-account-management
description: "Personal finance ledger/account management for creating accounts and recording balances, income, expenses, transfers, subscriptions, budgets, receipts, and review items with preview and confirmation."
version: 1.7.0
author: Colin + Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [finance, personal-accounting, ledger, accounts, budgeting, subscriptions, receipts, blueprint, automation]
    blueprint:
      schedule: "0 8 * * *"
      deliver: origin
      prompt: >-
        Check the canonical personal-finance ledger for active subscriptions due today or overdue, using the bundled due-subscription query for today's date. If the ledger is missing or nothing is due, respond exactly [SILENT]. Otherwise send one concise message in the user's language with a complete confirmation preview for every due item: subscription name, expected charge date, billed amount and currency, payment account, balance impact, category, next billing date, and any base-currency conversion source, date, and calculation. For foreign currency, prefer an actual settled amount; otherwise search a dated reference rate for the charge date and clearly label it as an estimate. Ask whether each subscription is still active and was actually charged. Never write during the scheduled run. A reply confirming that a listed subscription is still active and charged authorizes only the exact previewed expense and support records; record them through the confirmed subscription-charge workflow. If the user says a subscription was cancelled, preview disabling it and require confirmation before changing it.
---

# Personal Account Management

## Overview

This skill helps Hermes maintain a lightweight personal finance ledger through confirmed chat workflows. It creates and initializes personal ledgers and accounts, then records income, expenses, transfers, account balances, budgets, subscriptions, receipt-derived spending, review items, and exchange rates without requiring a database.

The source of truth is the user's account book in the configured runtime data location. All finance mutations must be previewed first and written only after explicit user confirmation.

## When to Use

Load and use this skill whenever the user wants personal finance account-book work, especially when they ask to:

- create, initialize, open, or set up a personal ledger or account book;
- create the first account, add an account, set an initial balance, or name an account such as a cash wallet, bank card, credit card, or e-wallet;
- record income, expenses, transfers, reimbursements, refunds, salary, repayments, balances, subscriptions, budgets, receipts, bills, statements, exchange rates, currency conversions, or review items;
- check personal spending, cash flow, account balances, budgets, subscriptions, net worth, anomalies, or dashboard/account-view data.

Non-English users may ask for the same intents in their own language. Treat phrases that mean "create account book", "create account", "open account", "cash wallet", "initial balance", "bookkeeping", "income", "expense", "transfer", "budget", "subscription", "receipt", or "bill" as triggers for this skill.

Do not use this skill for business accounting, tax filing advice, investment recommendations, loan underwriting, or legal/financial advice.

## Routing and storage authority

This skill owns the canonical personal-finance ledger for Hermes. When this skill handles a personal ledger/account request:

- Do not ask the user where to store the ledger unless they explicitly ask for an export or integration outside this skill.
- Do not offer Markdown files, Notion databases, Obsidian vaults, spreadsheets, generic notes, or conversation-only memory as the source of truth.
- Do not invent storage paths, generated ids, schemas, filenames, or implementation details in chat.
- Use `$HOME/personal-account-management/account-book.json` as the sole canonical runtime account book, through the bundled `account_book.py` CLI with an explicit `--book` path. Never insert `.hermes`, `HermesData`, or another intermediate directory. Per-month transaction shards (`transactions/YYYY-MM.json`) are derived automatically by the CLI; never pass a shard as `--book`.
- If the user explicitly asks for an external destination, treat it as an export/sync request after the canonical ledger is updated, not as a replacement for the canonical ledger.

## First-run account bootstrap

For first-run prompts such as "create a ledger", "create an account", "create a cash wallet":

1. If the account book does not exist, initialize the canonical account book internally.
2. Collect only user-visible account details that are actually needed: account name, account type, currency, and initial balance.
3. Present a natural-language preview of the account that will be created. Do not expose paths, command names, JSON, ids, or storage choices.
4. Wait for explicit user confirmation.
5. After confirmation, immediately write the account with `upsert-account --confirmed` against the canonical account book. Do not merely acknowledge the confirmation and do not ask where to store the ledger.
6. Reply in natural language that the account is saved and the user can continue bookkeeping.

## Highest-priority chat contract

Everything below that mentions commands, flags, record fields, file names, error codes, JSON, storage paths, tools, or app-registration internals is operator-only implementation guidance. Use it to run tools, but never quote it or summarize it to the user unless the user explicitly asks for technical implementation details.

When replying in ClawChat:

- Reply in the user's language. Use natural finance/product terms instead of implementation terms.
- Do not mention command names, command modes, CLI flags, tool names, raw validation wording, raw status values, raw review reason codes, generated ids, JSON fields, storage paths, schema/version terms, file names, reference names, memory/self-improvement notes, or internal retry/debug language.
- Do not ask the user to choose a ledger storage backend for normal personal-account creation. Never suggest Markdown, Notion, Obsidian, spreadsheets, or conversation-only memory as the ledger source of truth unless the user explicitly asks for export/sync options.
- Code blocks in this file are for tool execution only. Never copy code-block words or flags into a user-facing chat reply.
- Translate every internal result before sending: a preview result means "pending confirmation"; a successful write means "saved/written"; a validation success means "the account book check passed"; a missing account error means "I cannot find that account; please choose an existing account or confirm creating a new one". If you hit an internal command mistake and retry successfully, do not narrate that mistake or mention option names; give only the natural final result.
- A user asking to preview, check, inspect, or "take a look" has not confirmed any write. Do not create accounts, categories, budgets, subscriptions, transactions, receipt records, or review flags until the user clearly says to write/confirm.
- Supporting records follow the same rule as transactions. If a request needs supporting accounts/categories/budgets/subscriptions/exchange rates, preview the complete bundle first. One explicit confirmation authorizes every item listed in that bundle; after confirmation, execute all listed items in order without asking for a second confirmation unless a new material user-visible item was not previewed.
- When the user asks Hermes to convert a foreign-currency amount and no actual settled base amount or user-supplied rate is available, search for a dated reference rate by following `references/exchange-rate-lookup.md`. Never invent a rate or silently use today's rate for a historical transaction.
- If the user signals a possible duplicate, do not auto-write. Surface the existing matching record in natural language and ask whether to treat it as duplicate, not-duplicate, or edit the fields. See `references/duplicate-detection.md` for wording guidance.
- If the user asks to enable personal-account-management liveware, ask for the app display name first. Offer the default localized product name "Account Book" and allow a custom name. Wait for the user's choice; do not activate with the default silently unless the user already supplied or confirmed it in the same turn.
- Never run ad-hoc shell/Python snippets or one-off ledger-inspection commands during a user-visible ClawChat flow. In particular, do not inspect the ledger just because the user says "if missing" or "if it does not exist". Those probes can surface raw command approval prompts. Instead, use the current confirmed conversation context when safe, ask a natural clarification, or present a conditional preview: "if it already exists I will reuse it; if not, I will create it after confirmation".

## Quick Reference

| User intent | Operator action |
|---|---|
| Create/init a personal ledger or first account | Initialize `ACCOUNT_BOOK` if needed, preview the account, wait for confirmation, then run `upsert-account --confirmed`. |
| Record income/expense/transfer | Build a candidate, preview amount/account/category/date/review state, wait for confirmation, then write with `--confirmed`. |
| Missing supporting account/category/budget | Preview the support record and target record as one bundle; one confirmation authorizes the whole bundle. |
| User suspects a duplicate transaction | Do not write. Surface the existing matching record in natural language and ask whether to treat it as duplicate, not-duplicate, or edit. |
| Convert foreign currency | Prefer the actual settled base amount; otherwise search a dated authoritative reference rate, show source/date/calculation, and confirm before saving it. See `references/exchange-rate-lookup.md`. |
| Scheduled subscription check | Query active subscriptions due today or overdue. Stay silent when none are due; otherwise send one complete charge preview and wait for confirmation. |
| User confirms a scheduled charge preview | Record the listed expense, update the payment-account balance and next billing date, and do not add anything not shown in the preview. |
| User reports a subscription was cancelled | Preview deactivation, confirm it, then disable future due reminders without recording an expense. |
| User asks where the ledger is stored | Explain only at a high level unless they ask for technical details; never make them choose a backend for normal use. |
| User asks for Markdown/Notion/Obsidian export | First keep the canonical ledger updated here; treat external destinations as optional export/sync work. |
| Static ledger cannot be used by this version | Stop the pending operation. Do not convert, rewrite, or import it; creating a replacement ledger is a separate explicit operator action. |
| Correct a completed month from a statement | Preview the complete resulting account state with `revise-balance-snapshot --dry-run`, then append the revision only after confirmation. |

## Scheduled subscription checks

This skill is also an opt-in automation blueprint. Its suggested job runs daily at 08:00 in the configured Hermes timezone and delivers to the chat where the automation was accepted. Installing the skill only creates a suggestion; it never schedules itself without user acceptance.

For every scheduled run:

1. Use `list-due-subscriptions` with today's date against the canonical account book. It returns active, reminder-enabled items due today or overdue and suppresses a due date that already has a linked charge.
2. Return `[SILENT]` when the account book is absent or no subscription is due.
3. Group all due items into one natural-language message. Show the complete expense candidate and ask the user to confirm that each subscription remains active and was actually charged.
4. Do not mutate the ledger from the scheduled run. The user's affirmative reply is the explicit confirmation for exactly the previewed bundle; then use the normal confirmed charge workflow.
5. If the user says an item is cancelled, preview setting it inactive and wait for confirmation. After confirmation, use `set-subscription-status`; do not record a charge.
6. For foreign currency, follow `references/exchange-rate-lookup.md`. Never reuse a stale subscription estimate silently for a new charge date.

See `references/subscriptions.md` for the due, confirmation, cancellation, and catch-up contract.

## Runtime paths

The Python CLI does not parse environment variables. All path resolution happens through explicit CLI flags (`--book`, `--template`, `--receipt-file`, `--ocr-json`). The shell resolves the standard `HOME` variable and the Hermes-provided `HERMES_SKILL_DIR`; Python still requires an explicit `--book` path.

Use stable user-data paths for mutable records. Do not store user ledgers inside the skill directory. Do not ask the user to choose this internal path during normal account-book creation.

```bash
ACCOUNT_DATA_DIR="$HOME/personal-account-management"
ACCOUNT_BOOK="$ACCOUNT_DATA_DIR/account-book.json"
```

`ACCOUNT_DATA_DIR` is always directly under the active user's standard `HOME` and survives skill upgrades. Do not insert `.hermes`, `HermesData`, or another intermediate directory. Hermes exposes the loaded package directory through `HERMES_SKILL_DIR`; use it for bundled scripts and templates instead of assuming an installation path.

## Monthly transaction shards

The CLI's `--book` flag value points at `account-book.json`; per-month transaction shards under `transactions/YYYY-MM.json` are derived automatically by the CLI. Do **not** pass a transaction shard as `--book`; it is not a separate ledger.

## Monthly recorded balance history

New ledgers start with static schema v3 and an empty monthly balance history. The first confirmed account creation records the first current-month account state. Every later confirmed write that changes one or more account balances updates that same current natural-month state as part of the already previewed financial bundle. A write using `--no-balance-update` does not change balance history.

Only static schema v3 is supported. An unsupported ledger is never converted or rewritten by the Skill, dashboard, BOOT, or Liveware startup. Do not reinterpret its accounts as a starting snapshot. If the operator deliberately creates a new ledger, it begins empty and records its first monthly state with the first confirmed account creation.

A backdated transaction changes today's recorded balances and the current recorded month only. It does not prove or rewrite an older month's closing state. If the user has a bank or wallet statement for a completed month, use a separately confirmed revision. Patch input may name only corrected accounts, but the user-facing preview must show every resulting account balance and the complete base-currency/foreign-currency summary. When no earlier state exists, a complete account-state input is required.

```bash
REVISION_PREVIEW="$(python "$HERMES_SKILL_DIR/scripts/account_book.py" revise-balance-snapshot \
  --book "$ACCOUNT_BOOK" \
  --month 2026-06 \
  --account-balance "acct_cash_wallet=90.00" \
  --reason "Confirmed against June statement" \
  --dry-run)"
REVISION_TOKEN="$(printf '%s' "$REVISION_PREVIEW" | python3 -c 'import json,sys; print(json.load(sys.stdin)["confirmation_token"])')"

# Run only after the user confirms every account in the resulting state.
python "$HERMES_SKILL_DIR/scripts/account_book.py" revise-balance-snapshot \
  --book "$ACCOUNT_BOOK" \
  --month 2026-06 \
  --account-balance "acct_cash_wallet=90.00" \
  --reason "Confirmed against June statement" \
  --confirmed \
  --confirmation-token "$REVISION_TOKEN"
```

Do not translate user account labels in revision previews. Do not claim that an unavailable month has zero assets; say that its balance history is unavailable.

## Core commands

Initialize an empty ledger and runtime directories:

```bash
python "$HERMES_SKILL_DIR/scripts/account_book.py" init \
  --book "$ACCOUNT_BOOK" \
  --template "$HERMES_SKILL_DIR/templates/account-book.example.json"
```

Preview an account before writing:

```bash
python "$HERMES_SKILL_DIR/scripts/account_book.py" upsert-account \
  --book "$ACCOUNT_BOOK" \
  --id acct_cash_wallet \
  --name "Cash Wallet" \
  --type asset \
  --currency CNY \
  --balance 100 \
  --description "Cash on hand" \
  --display-group "Cash" \
  --dry-run
```

Write the account only after explicit confirmation:

```bash
python "$HERMES_SKILL_DIR/scripts/account_book.py" upsert-account \
  --book "$ACCOUNT_BOOK" \
  --id acct_cash_wallet \
  --name "Cash Wallet" \
  --type asset \
  --currency CNY \
  --balance 100 \
  --description "Cash on hand" \
  --display-group "Cash" \
  --confirmed
```

Preview a chat-derived transaction before writing:

```bash
python "$HERMES_SKILL_DIR/scripts/account_book.py" add-transaction \
  --book "$ACCOUNT_BOOK" \
  --date today \
  --kind expense \
  --amount 72 \
  --currency CNY \
  --title "Ride hail" \
  --category "Transport" \
  --account "Cash Wallet" \
  --source-text "Taxi ride cost 72 yesterday; it may have been charged twice" \
  --dry-run
```

After the user confirms amount, source, category, account, date, and review state, write with explicit confirmation:

```bash
python "$HERMES_SKILL_DIR/scripts/account_book.py" add-transaction \
  --book "$ACCOUNT_BOOK" \
  --date today \
  --kind expense \
  --amount 72 \
  --currency CNY \
  --title "Ride hail" \
  --category "Transport" \
  --account "Cash Wallet" \
  --source-text "Taxi ride cost 72 yesterday; it may have been charged twice" \
  --needs-review \
  --review-reason duplicate_check \
  --confirmed
```

Import a receipt only after OCR has already been handled by `ocr-and-documents` or explicit fields are available:

```bash
python "$HERMES_SKILL_DIR/scripts/account_book.py" import-receipt \
  --book "$ACCOUNT_BOOK" \
  --receipt-file "$ACCOUNT_DATA_DIR/inbox/coffee.pdf" \
  --ocr-json "$ACCOUNT_DATA_DIR/inbox/coffee.ocr.json" \
  --category "Food and Coffee" \
  --account "Cash Wallet" \
  --dry-run
```

Configure liveware once, then start the local service and bind the saved app:

```bash
SETUP_JSON="$(python3 "$HERMES_SKILL_DIR/scripts/setup_liveware.py" \
  --app-name "Account Book")"
APP_ID="$(printf '%s' "$SETUP_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["app_id"])')"
"$HERMES_SKILL_DIR/scripts/start_liveware.sh" "$APP_ID" \
  --book "$ACCOUNT_BOOK" \
  --app-name "Account Book"
```

`setup_liveware.py` is a first-use operation: it owns login, app list/create, ClawChat registration, and app-id persistence. Local state may identify the Liveware app, but Setup always checks the current ClawChat account before deciding that registration already exists; it skips `register_app` only when that account already contains the same app id. `start_liveware.sh` owns local server startup and tunnel binding. On later starts, pass the saved app id directly and do not repeat setup. Report only the natural user-facing outcome; do not expose commands, paths, ids, tokens, logs, or raw output.

## First-run bootstrap command pattern

`init` creates an empty ledger; it does not seed any accounts. After the ledger file exists, accounts, categories, and budgets must be added with the same preview -> confirm -> write pattern. The command accepts user-facing monetary amounts, for example `100` means 100.00 in the selected currency, and stores normalized values internally.

Preserve user-facing names exactly. Internally you may use generated ids in CLI fields when needed, but do not show those ids to the user.

```bash
python "$HERMES_SKILL_DIR/scripts/account_book.py" upsert-category \
  --book "$ACCOUNT_BOOK" \
  --id cat_food \
  --name "Food" \
  --kind expense \
  --group "Daily Life" \
  --dry-run

python "$HERMES_SKILL_DIR/scripts/account_book.py" upsert-category \
  --book "$ACCOUNT_BOOK" \
  --id cat_food \
  --name "Food" \
  --kind expense \
  --group "Daily Life" \
  --confirmed
```

Minimal budget setup invocation:

```bash
python "$HERMES_SKILL_DIR/scripts/account_book.py" upsert-budget \
  --book "$ACCOUNT_BOOK" \
  --id budget_food_current \
  --name "Food Monthly" \
  --category "Food" \
  --period monthly \
  --limit 500 \
  --currency CNY \
  --confirmed
```

## User-facing chat style

Keep implementation details internal. In chat, show a human-readable preview such as date, amount, account name, category name, title, review wording, and expected balance change. Do not paste command output, JSON records, generated handles, storage fields, error codes, or technical status words into the chat unless the user explicitly asks for technical details. If a value is ambiguous, ask naturally in the user's language.

When the user asks for a generated report or export, provide the available file or direct viewing link rather than only summarizing it.

Keep routine replies concise. Lead with the result and the next action; provide more detail only when requested or necessary for a safe financial decision.

For bootstrap previews, use this style instead of raw records:

```text
I will prepare these account-book settings and write them only after you confirm:
- Account: Cash Wallet, asset account, balance CNY 100.00
- Category: Food, for expenses
- Monthly budget: Food, limit CNY 500.00

Should I write these now?
```

For transaction previews, use this style instead of raw records:

```text
I will record this expense after you confirm:
- Date: today
- Amount: CNY 12.34
- Account: Cash Wallet
- Category: Food
- Title: Lunch
- Review: no review needed
- Balance change: CNY 100.00 -> CNY 87.66

Should I write it?
```

Use this two-step pattern:

1. Produce a candidate record without mutating the ledger.
2. Show the candidate to the user and ask whether amount, source, category, account, date, and review state are correct.
3. Only after the user confirms, immediately run the same candidate in write mode. Do not merely acknowledge the confirmation. Then report the result in natural language, without generated handles or technical status words.
4. If a confirmed step fails because of an internal invocation issue, fix it silently and continue when the user-visible action is unchanged. If the user-visible action changes, ask again in natural language before writing.
5. If the action changes data visible in personal-account-management liveware, the user can refresh it; do not run read-only probes unless asked.
6. If the user asks to install or enable personal-account-management liveware, first ask them to accept the default display name or enter a custom one; after they choose, use the setup/start script internally and answer only in natural product language. Do not give terminal commands, tool names, paths, ids, URLs, or implementation notes unless they explicitly ask for technical steps.

Commands that create transactions or receipt-derived records must reject writes unless explicit confirmation is present.

## Confirmation-preview addition

When a candidate changes balances, include one natural line after the before/after balances:

```text
- Monthly balance history: this month's recorded account state will reflect these resulting balances
```

This is part of the same financial bundle, not a second mutation and not a second confirmation. Omit the line for `--no-balance-update` because neither current balances nor the monthly account state changes.

## Dashboard source, build, and runtime

The dashboard source is `liveware/frontend/`; committed runtime output is `liveware/dist/`. Node is build-time only. Runtime startup serves the committed files with Python and must not run npm, install dependencies, build assets, initialize a ledger, or convert unsupported static data.

When intentionally refreshing committed output:

```bash
cd "$HERMES_SKILL_DIR/liveware/frontend"
npm ci
npm run check:selectors
npm run check
npm run build
npm run verify:dist
```

For freshness-only verification, run `npm run verify:dist` without a preceding build so stale committed output cannot be overwritten before comparison. Never ship `node_modules/`. `liveware/index.html` no longer exists; `liveware/dist/index.html` is the only dashboard entry and `/assets/*` is the only generated static subtree served by Python.

The dashboard is read-only. It uses the API's ledger-timezone `current_month`, one natural-month selection across every section, and silent serialized polling. Analysis generation is initiated from the selected month, but status and report publication remain server-owned and recover after reload, timeout, or a concurrent-run response. The dashboard never performs a financial mutation.

## Included files

- `references/data-contract.md` - ledger, source, review, subscription, exchange-rate, and account-view data rules.
- `references/cli-commands.md` - supported ledger operations and their write boundaries.
- `references/conversation-workflow.md` - confirmation-first account, transaction, receipt, subscription, and review workflows.
- `references/receiving-receipts.md` - receipt extraction and transfer-versus-expense handling.
- `references/subscriptions.md` - subscription creation, due checks, charges, cancellation, and cadence rules.
- `references/transfer-category.md` - transfer category conventions.
- `references/duplicate-detection.md` - duplicate handling and user-facing recovery wording.
- `references/exchange-rate-lookup.md` - dated exchange-rate source selection and confirmation workflow.
- `references/missing-category-bundle-preview.md` - bundled preview for a missing category and its transaction.
- `references/monthly-analysis-report.md` - monthly financial analysis and report format.
- `prompts/finance-analysis/SKILL_PROMPT.md` - monthly analysis brief used by the dashboard report action.
- `templates/account-book.example.json` - empty ledger template.
- `scripts/balance_history.py` - pure monthly balance-history capture, revision, validation, and resolution rules shared by the CLI, dashboard service, and analysis.
- `scripts/account_book.py` - ledger CLI for validation, confirmed writes, review, receipts, subscriptions, and due checks.
- `scripts/analysis_helpers.py` - monthly analysis calculations.
- `scripts/setup_liveware.py` - liveware login, app creation/reuse, ClawChat registration, and app-id persistence.
- `scripts/start_liveware.sh` - local dashboard service startup and tunnel binding for a saved app id.
- `liveware/serve.py` - local dashboard service.
- `liveware/frontend/` - Svelte dashboard source and deterministic build tooling.
- `liveware/dist/` - committed read-only dashboard runtime output.

## Receipt and OCR boundary

Use the related `ocr-and-documents` skill when the user provides a PDF, screenshot, or scanned receipt that needs text extraction. This skill stores the extracted facts and evidence in transaction `source`; it does not embed OCR models or heavy OCR dependencies.

For every receipt-derived candidate, confirm the amount, merchant, date, category, payment method, and source file with the user before writing.
