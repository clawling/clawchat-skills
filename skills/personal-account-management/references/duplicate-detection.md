# Duplicate detection on the candidate record

Operator-only reference. Never quote command names, ids, internal status values, error codes, generated handles, JSON fields, or scan mechanics to the user.

## Principle

When the user might be entering the same transaction twice, the safe behavior is:

1. Check the candidate internally.
2. If it looks like a duplicate, do not write immediately.
3. Explain the match in natural finance language.
4. Offer choices and wait for the user's decision.

## User-facing wording

Good:

```text
This looks very likely to be a duplicate: there is already a lunch entry today for ¥12.34, using Test Cash Account and the Dining category.

What would you like to do?
1. It is a duplicate; skip writing it
2. It is not a duplicate; write it as a second entry
3. Change the amount/title/time and preview again
```

Bad:

- mentioning generated ids;
- mentioning command names or scan names;
- mentioning raw duplicate codes;
- dumping JSON or internal match fields.

## If the user says it is not a duplicate

Preview a second, distinguishable transaction in natural language before writing. If a title suffix is needed internally, surface it as a user-visible title choice:

```text
To distinguish it from today's existing "Lunch" entry, I suggest writing this title as "Lunch - 2".
The amount, account, and category stay the same. Confirm that I should write it this way?
```

Do not silently change the title. If the user insists on the exact same title, handle the internal uniqueness requirement without exposing the generated handle.

## If the user edits the candidate

Treat it as a fresh preview and ask for confirmation again. Do not chain silent writes.

## Post-write auto-flag (CLI detected a duplicate AFTER writing)

The CLI's duplicate scanner can return a successful `status: added` while
setting `needs_review: true` and stamping a `possible_duplicate` reason on
the returned record (with `source.duplicate_candidates: [<other_id>]`
and a populated `review.history`). This is a *successful write with a
flag*, not a refused write — the ledger has already been updated.

What surfaced a real near-miss this way: bulk import from a balance-detail
screenshot — same merchant, same amount, different day (Lawson ¥23.00 on
07-02 and 07-03). The CLI did not know both are real, so it auto-flagged
the second one. The user will then say "keep both" / "Lawson was two
transactions" and expect you to clear the flag without rewriting.

Required workflow:

1. After any `add-transaction --confirmed` call, **read the returned
   envelope for `needs_review: true`** before reporting success. The CLI
   is allowed to write *and* flag in the same call; do not interpret it as
   "the second write failed".
2. In the natural-language reply, mention the flag in passing: "The 7th
   entry was automatically marked as pending review because the system
   thinks it may be a duplicate of Lawson ¥23.00 from 07-02 — this is
   because the same store charged the same amount on different dates, but
   it is actually two real transactions. When you have a moment, tell me
   'keep both' and I will mark it as approved."
3. Wait for explicit confirmation before calling
   `resolve-review --status resolved`. Do not auto-resolve just because the
   duplicate candidate is "obviously the same pattern" — the user knows
   their own payment cadence; trust their judgment.
4. The user may say "keep both" / "not a duplicate" / "Lawson was two
   transactions" — any of these maps to `--status resolved --resolution
   "not_duplicate: <brief justification>"`. Keep the resolution string to
   one short clause, never paste internal ids or candidate counts.
5. After resolution, report only the natural outcome: "✅ The Lawson entry
   from 07-03 has been marked as approved; it really was two transactions."

Failure mode this prevents: silently leaving `needs_review: true` on the
record, which clutters every subsequent scan-anomalies / list-review call
with a false-positive the user already resolved verbally.
