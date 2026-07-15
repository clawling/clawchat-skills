# CLI command inventory

Operator-only reference. Every subcommand of `scripts/account_book.py`. Subcommands not listed in SKILL.md but used by the skill's maintenance flows. Do not quote flag names, paths, or JSON output to the user.

## Ledger lifecycle and balance history

| Command | Purpose and write boundary |
|---|---|
| `init` | Create a new static-schema-v3 ledger with empty `balance_snapshots`; it does not create an account or a snapshot. |
| `validate` | Require static schema v3 and validate every schema-v2 transaction-shard object. Any other static version returns `unsupported_static_schema` without writes. |
| `revise-balance-snapshot --month ... --account-balance ... --reason ... --dry-run/--confirmed` | Preview or append a completed-month revision. A patch expands against the latest resolvable state; when no prior snapshot exists, `--accounts-json` supplies `base_currency`, `timezone`, and a complete account state. |

`revise-balance-snapshot` is a finance-data write and obeys the same preview/confirmation invariant as transactions. Its dry-run returns an opaque `confirmation_token`; the confirmed invocation must pass that exact token. The token binds the complete candidate and loaded-ledger state while ignoring regenerated snapshot timestamps. A mismatch returns `preview_changed` and writes nothing. There is no static-ledger migration command.

## Read-only

| Command | Purpose |
|---|---|
| `init` | Bootstrap an empty book from a template. |
| `validate` | Verify the merged book (static + all shards) is consistent. Returns `{"status": "valid"}` or lists errors. |
| `list-review` | Return every transaction currently in `needs_review` state. |
| `list-due-subscriptions --date ...` | Return active, reminder-enabled subscriptions due on or before the requested date, excluding a due date that already has a linked charge. Used by the daily blueprint. |
| `scan-anomalies --dry-run` | Return candidate anomalies (duplicates, suspicious patterns). Must be re-run with `--confirmed` to actually flag them. |

## Static-data writes

These touch only `account-book.json`; transactions are unaffected.

| Command | Writes |
|---|---|
| `upsert-account` | `accounts[]` |
| `upsert-category` | `categories[]` |
| `upsert-budget` | `budgets[]` |
| `add-subscription` | `subscriptions[]` |
| `set-subscription-status` | Toggle one subscription's active state after preview and confirmation. |
| `add-exchange-rate` | `exchange_rates[]` |

All of these are idempotent on `id`. Re-running with the same id returns `{"status": "updated"}`.

`upsert-account` changes the current account state and therefore also creates or updates the current natural-month snapshot in the same confirmed write. Category, budget, subscription-definition, subscription-status, and exchange-rate writes do not change account balances and do not capture a snapshot.

## Transaction writes

| Command | Effect |
|---|---|
| `add-transaction` | Append to the month shard matching `tx.date[:7]`. |
| `flag-transaction --id ... --reason ...` | Mark an existing transaction as `needs_review`. |
| `resolve-review --id ... --resolution ...` | Move a transaction out of `needs_review`. |
| `charge-subscription --subscription ...` | Generate a transaction from a subscription definition + advance `next_billing_date`. May require `--base-amount` when the subscription currency differs from the payment account's currency. |
| `import-receipt` | Same as `add-transaction` plus OCR-derived `source` fields (`source.type: "receipt"`, `source.ocr_engine`, `source.line_items`). |

There is no `update-transaction` or `delete-transaction` command. To move a transaction across months, load the book with `account_book.load_book`, mutate `date` in memory, and call `account_book.save_book` — `save_book` will rebucket and unlink empty shards.

The following balance-affecting commands update the current natural-month snapshot when their `balance_updates` list is non-empty:

- `add-transaction` for income, expense, and both transfer legs;
- `charge-subscription`;
- `import-receipt`.

Their dry-run result includes `balance_snapshot` with create/update mode, recorded month, revision, affected account ids, and a resulting base/foreign summary. It is a deterministic side effect of the displayed balance changes. Confirmed execution writes the transaction, balances, and snapshot from the same in-memory candidate. A `--no-balance-update` write returns `balance_snapshot: null` and leaves every snapshot unchanged.

Every command other than explicit `init --force` rejects an existing non-v3 static ledger with `unsupported_static_schema`. Rejection never rewrites static data or transaction shards.

## Side-effect surface

- Every CLI write updates `metadata.updated_at` on the static file. Transaction writes update only their affected shards; static-only commands preserve every shard byte.
- Account balances change via `apply_balance_updates` after a confirmed transaction write; subscriptions, exchange rates, and budgets do not change balances.
- Multi-currency transactions (e.g. USD subscription charging a CNY account) require `--base-amount` or `--exchange-rate-id`, otherwise `invalid_balance_update` is raised.

## Confirmation invariant

Subcommands that create transactions or receipt-derived records reject writes unless `--confirmed` (or `--dry-run` for previews) is passed. Dry-run output is a candidate, not ledger state.

## Version and persistence surface

- Static `account-book.json`: schema version 3 only; includes `balance_snapshots`.
- Transaction shards: schema version 2; `save_book` must never stamp them with the static version.
- `save_static_book` updates account/snapshot state without rewriting transaction shards.
- Historical revisions append new rows and never delete or overwrite an earlier revision.
- Ordinary backdated transactions use their effective date for shard/report placement but use the command's recorded month for current balance history. They never rewrite a completed snapshot.
