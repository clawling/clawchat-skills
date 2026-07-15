# Conversation Workflow

This reference guides Hermes when creating or changing personal finance records through chat. The primary safety rule is confirmation before mutation: never write transaction-like records or supporting setup records until the user confirms the candidate amount, source, category, account, date, and review state.

## Interaction policy

Ask a clarification when missing information changes accounting behavior:

- Amount.
- Income vs expense vs transfer.
- Category or purpose for a large or ambiguous payment.
- Subscription cadence or renewal date.
- Currency when the amount is not clearly local.
- Account for income/expense, and both source and destination accounts for transfers, because confirmed writes update balances by default.
- Receipt source details when OCR may have misread merchant, amount, date, or invoice number.

Do not ask for information that is obvious and low-risk, but still show the candidate before writing.

## Confirmation checklist

Before running any write command with explicit confirmation, present a concise candidate:

| Field | Confirm with user |
| --- | --- |
| Date | Is the transaction date correct? |
| Kind | Is this income, expense, or transfer? |
| Amount and currency | Is the amount exactly right? |
| Category | Is the category appropriate? |
| Account | Is the payment/receiving account correct? For transfers, are both source and destination accounts correct? |
| Source | Does the source text, receipt file, or subscription link match? |
| Review state | Should this stay under review? |

If the user says yes, run the same candidate in write mode. If they correct a field, update the candidate and preview again when the correction is material.

## Ambiguous payment flow

When the user says only "paid / charged / debited + amount":

1. Keep the amount, date, and original text in working memory.
2. Ask whether it is an expense, transfer, repayment, or prepayment.
3. If the user answers with an item or merchant, infer category.
4. If the category is new and durable, add or update it after confirmation.
5. Preview the transaction candidate without writing.
6. Ask the user to confirm amount, source, category, account, and date.
7. Write with explicit confirmation; balances update automatically unless `--no-balance-update` is deliberately used.
8. Tell the user exactly what was recorded.

## Receipt or invoice flow

When the user uploads a receipt, invoice, statement, screenshot, or bill:

1. Use `ocr-and-documents` to extract text when OCR or document parsing is needed.
2. Identify candidate date, merchant, total, currency, category, payment method, invoice number, and source file.
3. Preview the receipt transaction candidate without writing.
4. Show the candidate to the user and explicitly ask whether amount, source, category, and payment method are correct.
5. If any field is uncertain, say which visible value needs checking and explain why in natural language. Never expose internal review field names, status values, or reason codes such as `needs_review`.
6. Write only after the user approves.
7. Let the user refresh the dashboard; do not run read-only dashboard probes unless asked.

Example confirmation prompt:

> I identified one expense from the uploaded receipt: 2026-07-02, Manner Coffee, ¥86, category Dining and Coffee, paid with Alipay. Please confirm whether the amount, receipt, category, and payment method are correct.

## Subscription flow

When the user mentions a subscription:

1. Determine amount, currency, cadence, category, next billing date, and payment account when known.
2. Preserve original currency. Do not invent exchange rates. If conversion is requested and no settled amount or user-supplied rate exists, follow `exchange-rate-lookup.md` to search a dated reference rate.
3. Preview the subscription candidate.
4. Ask the user to confirm cadence, amount, category, and next billing date.
5. Write only after confirmation.

When recording an actual charge, link the transaction back to `subscription_id` and check whether the charge is early, duplicate, or outside the expected amount.

For a daily blueprint reminder, the scheduled turn is read-only. Present all due or overdue items as one complete charge preview. If the user confirms that a listed subscription remains active and was charged, that reply is the write confirmation for the exact previewed expense. If the user says it was cancelled, preview deactivation separately and confirm it before changing the subscription.

## Foreign-currency conversion flow

1. Preserve the original amount and currency.
2. Prefer the actual settled base-currency amount from the user, receipt, card, bank, or wallet statement.
3. If the user asks Hermes to find the conversion and no settled amount is available, follow `exchange-rate-lookup.md`: search the exact pair and transaction date, open a reputable source, and treat a searched market rate as an estimate.
4. Preview the source, rate date, pair direction, rate, conversion, and resulting transaction/account effect in natural language.
5. Wait for explicit confirmation before saving either the exchange-rate record or the transaction.
6. If no reliable dated source can be found, keep the original currency and explain that the converted amount still needs confirmation; never fabricate a rate.

## Review flow

When a transaction is marked for review:

1. Explain the reason in natural language.
2. Ask the user whether to keep it under review, correct it, or resolve it.
3. Persist the result only after confirmation.
4. Let the user refresh the dashboard so review counts and row states match the ledger.

## Category creation

Add a category only when all are true:

- The user names a durable spending or income type.
- Existing categories do not cover it cleanly.
- It will likely be useful in future reports.

Use tags for merchant names, one-off event names, and extra detail.

## Income-category bootstrap pattern

A common bootstrap case the user will hit: they say "record an income, category Income" (or any phrasing that names an income category), but the freshly initialized ledger has no `kind=income` category yet — only the expense categories they set up. The CLI preview will return `review.status = needs_review` with reason `unknown_category` even though the user clearly intends to write this record.

Do **not** present the transaction as "needs review" and stop. The user already told you the category name. Bundle the two writes in one preview:

1. **Create the income category first** (with the natural name the user gave, e.g. `Income`; `kind=income`; do not translate it).
2. **Then write the income transaction** in the same bundle, after the category exists, so the final write lands with `review.status = clear`.

Surface this in the preview naturally, e.g.:

> ⚠️ The ledger does not yet have a category named "Income". I am preparing two things now, and I will write both after you confirm:
> 1. New category: Income (for income)
> 2. Income record: ... (remaining fields)
>
> 💡 Because the category is created before the transaction is written, the review state after saving will automatically become "no review needed".

One explicit confirmation authorizes both items. This avoids forcing the user into a confusing "needs review → how do I resolve it?" round-trip when the gap is obvious and resolvable in one step. The same pattern applies to any kind mismatch (for example, when the user names a transfer category that does not exist yet during bootstrap).

## Preserve exact user-facing names (no translation)

When a user names an account, category, budget, transfer grouping, or transaction title, **use that exact string verbatim** in previews, ledger records, and the post-write summary. Do not translate it to English (`Test Cash`, `Food`, `Transfer`) and do not auto-suffix display groups with English defaults. Users will often restate this preference explicitly ("do not translate these names into English", "do not translate account names") — that is a binding signal, not optional flavor, and applies to every bundle step (not just the first).

## Missing-scaffolding preview (bootstrap and first records)

When the user asks for a transaction (income/expense/transfer/subscription) whose supporting record does not yet exist in the ledger, do **not** silently create the missing support record and then write the transaction in two hidden steps. Surface the support setup and the target record in a single preview so the user can confirm the bundle before any write happens.

Detection signals come from the current confirmed conversation context and safe account-book command results. If you are unsure whether a support record exists, do **not** run ad-hoc shell/Python snippets to inspect the ledger. When the user says "if it already exists / if it does not exist", build a conditional planned preview from the user's requested setup: "If it already exists, I will reuse it; if it does not, I will create it." Then ask for confirmation before any write.

Specifically:

- The named account does not exist or is uncertain. A transaction preview that depends on that account may be impossible. Do **not** create the account just to make the preview work; show a planned setup + transaction bundle instead.
- The named category does not exist or is uncertain. The user probably expects either "create the category first" or "put this one into pending review first". Ask naturally.
- The named budget does not exist or is uncertain. Include budget setup in the same bundle if the user asked for it.

Flow when support setup is missing:

1. Confirm what is present only from current confirmed context or safe account-book command results. Do not run one-off shell/Python ledger reads in a ClawChat flow because command approval prompts are user-visible. If unsure, use a conditional planned preview or ask naturally.
2. Preview or plan the missing support setup without writing it.
3. If the target transaction can be safely previewed without the missing setup, preview it. If it cannot, create a **planned preview** from the current balances and the user-provided amounts. Label it as "estimated balance change".
4. Present setup and target record in one natural-language preview. Example:

   ```text
   Here is the preview. The ledger currently does not have "Test Bank Card Account", so the "create account" step and the "transfer" need to be confirmed together:

   I will prepare 2 steps, and I will write both after you confirm:

   1. Create account: Test Bank Card Account, initial balance ¥50.00
   2. Record transfer: from Test Cash Account to Test Bank Card Account, amount ¥10.00
      - Test Cash Account: estimated ¥87.66 → ¥77.66
      - Test Bank Card Account: estimated ¥50.00 → ¥60.00
      - Review: no review needed
      - Budget impact: transfers do not count toward expense budgets

   Confirm both steps together?
   ```

**Multi-support bundle (account + category + transfer).** When the bundle needs both a new account and a new category (or a new transfer grouping), tag each item with reuse / new so the diff is obvious, and lead with a short "state check" sentence so the user can see what was actually found versus what was assumed:

   ```text
   Check complete ✅ "Test Bank Card Account" and the "Transfer" category do not exist yet, so they will both be created.

   📦 Reused / new items
   - Account "Test Cash Account": reused, balance ¥87.66
   - Account "Test Bank Card Account": new, asset account, initial balance ¥50.00
   - Category "Dining": reused
   - Category "Transfer": new, used for transfer grouping (transfers do not count toward income/expense budgets)

   💸 Transfer to be written
   - Date: today
   - Amount: ¥10.00
   - Type: transfer
   - Title: transfer
   - Category: transfer
   - Source account: Test Cash Account
   - Destination account: Test Bank Card Account
   - Review: no review needed

   📊 Estimated balance change
   - Test Cash Account: ¥87.66 → ¥77.66 (−¥10.00)
   - Test Bank Card Account: ¥50.00 → ¥60.00 (+¥10.00)

   Confirm writing everything in one batch?
   ```

5. After the user confirms, write the support setup first, then write the target record in the same batch. Do not skip the support setup if the target record depends on it.
6. In the post-write summary, list both records in natural language, for example "created account ...; recorded transfer ...". Do not show generated handles, raw fields, command output, or technical status words.

Edge cases:

- If the user explicitly says "write only the transaction, leave it pending review first" or "skip creating the category", respect that preference.
- If multiple support records are missing (for example a new account, a new category, and a new budget), group them in the same preview but preserve write order — accounts before categories, categories before the transaction, budgets last.
- This pattern is especially important during bootstrap when the ledger is fresh; once the ledger is mature, support gaps are rare and you can fall back to the standard single-record confirmation flow.

## Re-confirmation with nothing pending

If the user re-sends a confirmation phrase ("confirm write / confirm / okay / ok") but the previous batch is already written and no new preview is on the table, do **not** re-execute the last write or invent a new record. Re-running a confirmed write could silently double-count or duplicate the entry.

Instead, in one short natural-language reply:

1. Tell the user what is already saved (for example, "the previous batch is already written: account / category / budget / that lunch expense") so they know the work landed.
2. Recap the ledger's current state at a high level (for example, the account's current balance or the budget's used/limit).
3. Ask one clarifying question: record the next expense? Adjust the budget start point? Or something else?

The only exception is when the user is clearly answering a still-pending preview that was just presented in the same turn — that is a normal confirmation, run the write.

This pattern is especially important immediately after bootstrap or after recording a single transaction, when a repeated confirmation could otherwise duplicate the previous write.

## Monthly balance-history confirmation

Balance history is a financial record and follows confirmation-first rules.

### Unsupported account book

When the CLI reports `unsupported_static_schema`, stop the pending request. Do not inspect the old accounts as a starting state, offer conversion, or rewrite any file. If the user wants to begin again, creating a new empty account book is a separate explicit action and the normal first-account confirmation starts its monthly history. Keep implementation terms out of the user-facing reply; say only that the existing account book cannot be used by this version.

### Normal balance-changing writes

A transaction/account preview already shows every affected account's before and after balance. Add one concise line that the resulting balances will become this month's recorded account state. The user's confirmation authorizes the transaction/account change and that derived monthly state together. Do not ask for a second confirmation.

For `--no-balance-update`, explicitly say the transaction is history-only and current account balances will not change. Do not claim monthly account history changed.

### Backdated transactions

A transaction's effective date controls the month in which cash flow, budgets, search, and reports include it. Recording it later still changes current balances now. Never tell the user that the old month's asset balance will automatically change.

If this distinction matters, say:

> I will include this transaction in June's activity, but it changes the balance currently recorded now. It will not rewrite June's saved account balances unless you separately provide and confirm June's complete corrected state.

### Completed-month corrections

Use a historical revision only when the user supplies an authoritative balance, such as a bank/wallet statement or an explicit corrected month-end amount. A patch may begin with one corrected account, but before writing, show:

- the completed month;
- every account in the resulting state, preserving labels and native currencies;
- the base-currency net worth;
- each foreign-currency balance separately as unconverted;
- that this will become a new revision while the prior state remains retained;
- the user's natural reason/source.

If there is no earlier trusted state for that month or before it, ask for a complete account list; never fill missing accounts from current balances. One confirmation appends the complete revision. A later correction appends another revision rather than mutating the earlier one.

### First account

A new schema-v3 ledger has no snapshot until the first confirmed account creation. The first-account preview should say that the shown account state will also start monthly balance history for the current natural month. Merely initializing an empty ledger does not create a financial state.
