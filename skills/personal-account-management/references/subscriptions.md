# Subscriptions

Operator-only reference. Do not quote command names, option names, ids, raw fields, raw statuses, JSON, or troubleshooting details to users. Translate everything into natural-language previews and confirmations.

## Create vs charge

A subscription has two separate concepts:

1. The recurring definition: name, amount, cadence, payment account, category, and next billing date.
2. An actual charge: one expense transaction linked internally to that recurring definition.

User-facing explanation:

```text
I will handle this in two steps and write only after confirmation:
1. Create subscription: TestSub, ¥10.00 monthly, charged to the test cash account, next billing date 2026-07-01
2. Record one charge: ¥10.00, category Dining, account Test Cash Account

Confirm write?
```

Internally, write the subscription definition before trying to record a charge for it. If both are requested together, preview the two-step bundle first, wait for confirmation, then write them in order.

## Daily due-check blueprint

The skill frontmatter declares an opt-in blueprint scheduled for 08:00 each day in the configured Hermes timezone. Installation registers a suggestion; it does not silently create a cron job. The user must accept the suggestion before checks begin.

Each scheduled run uses the read-only `list-due-subscriptions` query for today. The query returns subscriptions that are:

- active;
- reminder-enabled;
- due today or overdue; and
- not already represented by a linked charge for that expected date.

If the ledger is missing or the result is empty, return `[SILENT]`. Otherwise send one consolidated natural-language message containing a complete charge preview for every due item: name, expected date, billed amount/currency, payment account, balance impact, category, next billing date, and conversion details where applicable.

The scheduled run is read-only. Ask whether each subscription is still active **and** the charge actually occurred. A clear affirmative reply is explicit confirmation for exactly the previewed bundle, so the follow-up chat turn may record the expense without asking again. If the user changes any material field, show the revised preview and reconfirm.

For a foreign-currency charge, prefer the actual settled base-currency amount. Otherwise search a dated rate for the charge date, show its source/date/pair direction/calculation, label it as an estimate, and include the rate support record in the same confirmation bundle. Never reuse the subscription's older estimate silently.

If the user says the subscription was cancelled, do not record an expense. Preview deactivation and require confirmation; after confirmation use `set-subscription-status --inactive`. An inactive subscription is excluded from future checks.

Overdue handling is intentionally one pending expected cycle per subscription. Recording a confirmed charge advances its next billing date. If several cycles were missed, later runs continue catching them up one cycle at a time rather than fabricating multiple charges in one turn.

## Date behavior

A charge uses the date supplied for that specific charge. If the user says “charge it on the next billing date”, use the next billing date. If the user says “it was charged today”, use today. If the date differs from the expected billing date, tell the user naturally:

- “This charge was earlier than expected; does it need review?”
- “This charge was later than expected; I will mark it for review.”

Do not expose raw review codes.

## What a successful charge changes

After confirmation, a charge should:

- record an expense;
- deduct the payment account balance;
- update the subscription's last charged date and next billing date internally;
- report the next billing date naturally to the user.

User-facing summary:

```text
Written: TestSub charged ¥10.00, account Test Cash Account.
Next billing date updated to 2026-08-01.
```

## Day-of-month drift

Monthly/quarterly renewals near month-end can move to the last day of shorter months. If this matters, explain naturally before writing many charges:

```text
Tip: If a subscription starts on the 31st, shorter months will fall on the last day of the month. Continue with this rule?
```

## Custom cadence

Custom cadence does not auto-compute future dates. If the user says “every 6 weeks” or any irregular schedule, ask for the next billing date and do not promise automatic scheduling.

## Missing supporting records

- Missing payment account blocks the write. Ask the user to choose an existing account or confirm creating a new one in the same preview bundle.
- Missing category can be handled by creating it first or by writing the charge as needing review. Prefer asking naturally whether to create the category.
- Missing budget is not required to record the subscription; ask naturally if the user wants one.

Do not run ad-hoc shell/Python/grep ledger probes in a ClawChat flow. Use confirmed conversation context, safe account-book results, or a conditional preview: “If it already exists, I will reuse it; if not, I will create it.”

## Foreign-currency subscriptions

Preserve the billed currency. If the user supplies a base-currency amount, store it internally. If not, mark the charge as needing review for missing conversion and tell the user naturally:

```text
This is a USD charge, but the CNY conversion amount is still missing; I will mark it for review.
```

Never invent exchange rates.

## Confirmation candidate fields

Before writing a subscription definition, show the user:

- name;
- amount and currency;
- cadence;
- next billing date;
- category;
- payment account;
- whether review is needed.

Before writing a charge, show the user:

- subscription name;
- charge date;
- amount and currency;
- payment account;
- balance impact;
- whether review is needed;
- next billing date after the charge.

## Balance-history effect of a charge

Creating or updating a subscription definition does not change balances and does not capture a snapshot. Recording an actual confirmed charge deducts the payment account and updates the current natural-month account state in the same confirmation bundle. Include that monthly-history effect after the account before/after balance in the charge preview.

A charge using `--no-balance-update` updates the linked transaction/subscription schedule only and leaves every account snapshot unchanged. A charge entered later with an older billing date belongs to that billing month's activity but never rewrites the older month's frozen assets.
