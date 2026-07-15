# Missing-category bundle preview pattern

When a transaction needs a category that does not exist yet in the ledger, surface the category creation AND the transaction in ONE preview, with a one-line heads-up that the category will be created. One user confirmation authorizes the whole bundle.

## Why

Splitting it into "should I create the category?" → wait → "now here's the transaction preview" → wait is two turns for what should be one. Users feel the friction. The bundle also makes the relationship between the supporting record and the target transaction visible, which is what the user is actually deciding on.

## Format (paste-ready, English)

```
⚠️ The category "<category name>" needs to be created first: I have not created "<category name>" in the ledger yet (currently only ...). If you want to continue the preview, I recommend creating a new "<category name>" category as well, with type <income/expense/transfer>.

I am preparing these bookkeeping settings, and I will write them after you confirm:
- Category: <category name>, used for <income/expense>
- <transaction kind> record:
  - Date: today (YYYY-MM-DD)
  - Amount: ¥<amount>
  - Account: <account name>
  - Category: <category name>
  - Title: <title>
  - Balance change: ¥<before> → ¥<after>

Confirm writing it? (If you want me to skip creating the new category and use an existing one instead, you can tell me that too.)
```

## Category `kind` mapping

| Transaction kind | New category kind |
| ---------------- | ----------------- |
| income           | `income`          |
| expense          | `expense`         |
| transfer         | `transfer`        |

When previewing, the category-setup line in the bundle must use the same kind word the user will see in chat ("used for income" / "used for expense" / "used for transfer").

## What NOT to do

- Don't probe the ledger first ("let me check if Income exists") — that surfaces internal commands/paths to the user.
- Don't ask "Should I create this category?" as a standalone question; that breaks the bundle into two turns.
- Don't silently auto-create the category without surfacing it in the preview — the user must see and confirm the supporting record.

## Worked example (this session)

User said: "Record one income: today I received a reimbursement of 20 yuan, deposit it into Test Cash Account, category Income."

Preview sent to user:

```
⚠️ The ledger does not yet have a category named "Income": I have not created that category yet (currently only "Dining"). If you want to continue the preview, I recommend creating a new "Income" category as well, with type income.

I am preparing these bookkeeping settings, and I will write them after you confirm:
- Category: Income, used for income
- Income record:
  - Date: today (2026-07-06)
  - Amount: ¥20.00
  - Account: Test Cash Account
  - Category: Income
  - Title: Reimbursement
  - Balance change: ¥87.66 → ¥107.66

Confirm writing it? (If you want me to skip creating the new category and use an existing one instead, you can tell me that too.)
```

User said "Confirm write" → category created (`kind=income`) + transaction written in the same turn.

## Balance-history line in the bundle

When the bundled transaction changes an account balance, add this after the before/after balance:

```text
- Monthly balance history: this month's recorded account state will reflect the resulting balance
```

The new category does not itself affect balance history. The one confirmation covers category creation, transaction, balance changes, and the derived current-month account state. Omit this line when the transaction is explicitly history-only with no balance update.
