# Transfers and transfer setup

Operator-only reference. Do not quote command names, field names, JSON, error codes, or internal setup details to the user. User-facing transfer replies should be natural Chinese previews.

## Principles

- Transfers move money between the user's own accounts; they are not income or spending.
- A transfer needs a source account and a destination account.
- A transfer may also need a neutral category label for grouping.
- Missing support records must not be silently created.
- If a support record is missing or uncertain, show a planned bundle and ask for confirmation before writing anything.

## Clean first-transfer flow

When the user asks for a transfer and the destination account or transfer category may not exist:

1. Do not run ad-hoc shell/Python snippets to inspect the ledger.
2. Use the current confirmed conversation context when safe; otherwise ask naturally or create a planned preview.
3. Present one bundle:
   - new/updated support records, if needed;
   - the transfer itself;
   - projected before/after balances;
   - statement that transfers do not count as spending.
4. Write support records first and the transfer second only after the user confirms the whole bundle.

Good user-facing preview:

```text
Preview below. I need to confirm the destination account and this transfer together:

I will prepare 2 steps and write them together after confirmation:

1. Create account: test bank card account, initial balance ¥50.00
2. Record transfer: from the test cash account to the test bank card account, amount ¥10.00
   - Test cash account: expected ¥87.66 → ¥77.66
   - Test bank card account: expected ¥50.00 → ¥60.00
   - Review: no review needed
   - Budget impact: transfers do not count toward spending budgets

Confirm writing both steps?
```

Bad user-facing behavior:

- Creating the destination account before the user confirms.
- Showing command output, JSON, generated handles, internal status words, or error codes.
- Saying you are checking command options or running a script.
- Asking for technical parameters instead of natural account/category choices.

## When to skip support setup

- If both accounts and a transfer category are already known from the current confirmed conversation context, preview the transfer directly.
- If the user is moving money to an external person/merchant rather than their own account, ask whether it should be a normal expense instead of a transfer.

## Balance-history effect

A confirmed transfer changes both account balances and updates one complete current natural-month account snapshot. The preview must show both before/after balances plus one monthly-history line; do not describe this as two snapshots or request a second confirmation. A backdated transfer appears in the older activity month but changes only the current recorded account state. Frozen historical balances require a separate statement-backed revision.
