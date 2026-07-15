# Personal Account Data Contract

This is an operator-only implementation reference. It contains storage field names and JSON examples for tool execution. Do not quote field names, JSON keys, schema/version terms, paths, raw status values, command names, tool names, ids, or self-improvement/debug notes to the user; translate them into natural finance wording.

User-facing translations:

- clear / false review state → "no review needed"
- review-needed state → "needs review" or "pending review" with a natural reason
- resolved review → "review completed"
- validation success → "ledger check passed"
- internal source/evidence fields → "source/evidence recorded" only when useful
- internal ids/handles → omit entirely

Static fields live in `account-book.json`, while transactions are stored in `transactions/YYYY-MM.json` shards. The CLI and HTTP layers expose them as one merged ledger. User data must remain outside the skill package at the configured account-book path.

## Storage versions

The static ledger and transaction shards are versioned independently:

- `account-book.json` uses static schema version `3` and owns profile, accounts, categories, budgets, subscriptions, exchange rates, balance snapshots, and metadata.
- `transactions/YYYY-MM.json` remains transaction-shard schema version `2`.
- Static ledger versions other than `3` are unsupported. CLI and dashboard reads reject them without conversion or mutation.

A writer must never use the static schema version for a transaction shard. There is no static-ledger migration path.

## Top level (static portion)

```json
{
  "schema_version": 3,
  "profile": {
    "base_currency": "CNY",
    "timezone": "Asia/Shanghai",
    "month_start_day": 1
  },
  "accounts": [],
  "categories": [],
  "budgets": [],
  "subscriptions": [],
  "exchange_rates": [],
  "balance_snapshots": [],
  "metadata": {
    "created_at": "2026-06-30T00:00:00+08:00",
    "updated_at": "2026-06-30T00:00:00+08:00"
  }
}
```

The static file does **not** contain a `transactions` field. Read paths synthesize it only from validated schema-v2 shard objects. Every static save preserves `balance_snapshots` and requires static schema v3.

## Per-month transaction shard

```json
{
  "schema_version": 2,
  "month": "2026-07",
  "metadata": { "updated_at": "2026-07-15T12:00:00+08:00" },
  "transactions": []
}
```

The filename month and payload month must match. Every transaction row must contain a canonical `YYYY-MM-DD` date whose `YYYY-MM` matches that same month; a mismatched row invalidates the shard and is never returned by a month projection. Shard revisions are outside this design.

## Profile

```json
{
  "base_currency": "CNY",
  "timezone": "Asia/Shanghai",
  "month_start_day": 1
}
```

`month_start_day` controls reporting periods when implemented. If omitted, reports use calendar months starting on day 1. Note: shards are always named `YYYY-MM` (calendar month), so reporting groups that respect `month_start_day` must aggregate in application code.

## Accounts

```json
{
  "id": "acct_cash",
  "name": "Cash and Checking",
  "type": "asset",
  "currency": "CNY",
  "balance_minor": 6820000,
  "description": "Salary cards, pocket change, money market funds",
  "display_group": "Cash and Checking",
  "active": true,
  "updated_at": "2026-06-30T12:00:00+08:00"
}
```

`type` can be `asset`, `liability`, or `receivable`. Balances are stored in minor units. Liability balances are positive in the ledger and rendered as negative by the liveware dashboard. Account records never appear in transaction shards — they are static.

## Categories

```json
{
  "id": "food_coffee",
  "name": "Dining and Coffee",
  "group": "daily",
  "kind": "expense",
  "description": "Meals, takeout, coffee, light meals",
  "active": true
}
```

`kind` can be `income`, `expense`, `transfer`, or `mixed`.

## Budgets

```json
{
  "id": "budget_food",
  "name": "Dining and Coffee",
  "group": "daily",
  "category": "Dining and Coffee",
  "period": "monthly",
  "limit_minor": 200000,
  "currency": "CNY",
  "active": true
}
```

Budget spending is calculated from transactions (across all shards) by matching `category`.

## Transactions

```json
{
  "id": "txn_20260702_coffee",
  "date": "2026-07-02",
  "kind": "expense",
  "title": "Coffee",
  "merchant": "Manner Coffee",
  "category": "Dining and Coffee",
  "account_id": "acct_cash",
  "to_account_id": null,
  "subscription_id": null,
  "amount_minor": 8600,
  "currency": "CNY",
  "base_amount_minor": 8600,
  "base_currency": "CNY",
  "exchange_rate_id": null,
  "tags": ["coffee"],
  "notes": "",
  "needs_review": false,
  "review_reason": "",
  "review": {
    "status": "clear",
    "reasons": [],
    "detected_at": null,
    "reviewed_at": null,
    "resolution": "",
    "history": []
  },
  "source": {
    "type": "chat",
    "source_text": "coffee today 86"
  },
  "created_at": "2026-07-02T12:00:00+08:00",
  "updated_at": "2026-07-02T12:00:00+08:00"
}
```

`kind` can be `income`, `expense`, or `transfer`. Ledger amounts are positive; display direction comes from `kind`. Confirmed writes update account balances by default: expense subtracts from `account_id`, income adds to `account_id`, and transfer moves from `account_id` to `to_account_id`. Use `--no-balance-update` only when recording history without changing balances.

### Transaction source

Every transaction must preserve how the candidate was created. Supported `source.type` values:

- `manual` — explicitly typed structured fields.
- `chat` — user chat text interpreted by Hermes.
- `receipt` — receipt, invoice, bill, screenshot, or statement evidence.
- `subscription` — generated from a subscription charge.
- `import` — imported from another structured data source.

Chat/manual source:

```json
{
  "type": "chat",
  "source_text": "I received my salary today, 10,000 yuan"
}
```

Receipt source:

```json
{
  "type": "receipt",
  "file": "receipts/2026-07-02-coffee.pdf",
  "source_text": "OCR or extracted receipt text",
  "merchant": "Manner Coffee",
  "invoice_number": "INV-20260702",
  "payment_method": "Alipay",
  "ocr_engine": "ocr-and-documents",
  "ocr_confidence": 0.86,
  "line_items": [
    {
      "description": "Latte",
      "quantity": 1,
      "amount_minor": 8600,
      "currency": "CNY",
      "category": "Dining and Coffee",
      "confidence": 0.86
    }
  ]
}
```

Receipt evidence is intentionally stored in `source`. The design does not introduce top-level attachment/import records.

### Review state

Keep `needs_review` and `review_reason` as simple mirror fields. Use `review` for structured state.

```json
{
  "status": "needs_review",
  "reasons": ["duplicate_charge", "uncertain_text"],
  "detected_at": "2026-07-02T12:00:00+08:00",
  "reviewed_at": null,
  "resolution": "",
  "history": [
    {
      "at": "2026-07-02T12:00:00+08:00",
      "action": "detected",
      "note": "same merchant, same amount, repeated within 72 hours"
    }
  ]
}
```

`status` can be `clear`, `needs_review`, or `resolved`.

## Subscriptions

```json
{
  "id": "sub_codex",
  "name": "Codex",
  "description": "AI coding tool",
  "category": "Work Costs",
  "amount_minor": 2000,
  "currency": "USD",
  "base_amount_minor": null,
  "base_currency": "CNY",
  "exchange_rate_id": null,
  "cadence": "monthly",
  "next_billing_date": "2026-07-30",
  "payment_account_id": "acct_credit",
  "active": true,
  "reminder": true,
  "tags": ["AI tools"],
  "last_transaction_id": null,
  "last_charged_date": null,
  "source": {
    "type": "chat",
    "source_text": "I subscribed to Codex for $20 a month"
  }
}
```

`cadence` can be `weekly`, `monthly`, `quarterly`, `yearly`, or `custom`.

## Exchange rates

```json
{
  "id": "fx_20260630_usd_cny",
  "date": "2026-06-30",
  "from": "USD",
  "to": "CNY",
  "rate": 7.25,
  "source": "user-provided",
  "estimate": false,
  "created_at": "2026-06-30T12:00:00+08:00"
}
```

Only use rates provided by the user or verified from a trusted dated source. A searched rate must retain its source URL, publication/effective date, pair direction, and `estimate: true`; an actual settled amount supplied by the user or statement takes precedence. If no reliable rate is available, keep the original currency and leave converted values empty. See `exchange-rate-lookup.md` for source selection, search, calculation, and confirmation rules.

## Balance snapshots

`balance_snapshots` is prospective recorded-state history, not a reconstruction from transactions. Each element is a complete account state for one natural calendar month in the profile timezone.

```json
{
  "id": "balance_snapshot_202607_r1",
  "month": "2026-07",
  "revision": 1,
  "created_at": "2026-07-13T18:00:00+08:00",
  "updated_at": "2026-07-31T20:15:00+08:00",
  "capture_type": "automatic",
  "reason": "",
  "base_currency": "CNY",
  "timezone": "Asia/Shanghai",
  "accounts": [
    {
      "id": "acct_cash",
      "name": "Cash and Checking",
      "type": "asset",
      "currency": "CNY",
      "balance_minor": 6820000,
      "description": "Salary cards and cash",
      "display_group": "Cash and Checking",
      "active": true,
      "updated_at": "2026-07-31T20:15:00+08:00"
    }
  ],
  "source": {
    "type": "automatic",
    "record_id": "txn_20260731_groceries"
  }
}
```

Rules:

- `month` is `YYYY-MM` and uses a calendar month. `profile.month_start_day` does not affect snapshots.
- Revision numbers are positive, unique, and contiguous within a month.
- Revision 1 for the open current month may be replaced after another confirmed balance-affecting write; its `created_at` remains stable and `updated_at` advances.
- Once a month is earlier than the current natural month, ordinary writes never modify any record for that month.
- A confirmed historical correction appends revision N+1. Earlier revisions remain byte-for-byte present.
- `capture_type` is `automatic` or `confirmed_revision`.
- Every revision stores complete account records plus the base currency and timezone known for that state. User labels are preserved exactly.
- Resolving a quiet month selects the latest revision from the latest source month at or before the selected month. Resolution never carries a later snapshot backward and never persists a synthetic row.
- A month before the earliest snapshot is unavailable. Current accounts, transactions, and exchange rates must not be used to invent it.

## Unsupported static ledgers

Only static schema v3 is accepted. `validate`, all ledger commands, `GET /api/book`, `GET /api/months`, and analysis startup reject any other static version with `unsupported_static_schema`. Rejection is read-only: no backup, conversion, snapshot, or transaction shard is created. Creating a replacement ledger is an explicit operator action, never a dashboard or startup side effect.

## Historical revisions

A correction may patch balances against a resolvable prior state, but the preview must display the complete resulting account list and totals. If no prior state can be resolved, `--accounts-json` must provide an object containing `base_currency`, `timezone`, and the complete `accounts` array; current profile context is not silently substituted for historical context. Confirmation appends a revision; there is no destructive edit or delete command.

## Confirmation invariant

Historical revisions are financial-data mutations. Dry-run writes nothing and returns an opaque digest of the complete candidate plus loaded-ledger state. Confirmation must return that digest; changed balances, revisions, months, metadata, or shard digests require a new preview. Confirmed execution persists exactly the bound complete state. Automatic current-month capture is authorized by the same confirmation as the balance-affecting account or transaction record. The preview includes its create/update mode, month, affected accounts, and resulting currency summary.

## Liveware dashboard data

The Python service remains read-only for ledger data.

### `GET /api/book`

Without a `month` query, this endpoint returns the raw merged schema-v3 ledger: static data, every valid schema-v2 transaction shard merged into `transactions`, and the full `balance_snapshots` revision history. A shard is valid only when its version is the integer `2`, its payload month matches its valid `YYYY-MM.json` filename, metadata is an object, and `transactions` contains only objects.

### `GET /api/book?month=YYYY-MM`

A month-filtered request is the polling projection for the dashboard. It reads only the selected transaction shard, rejects an invalid shard payload as empty, and returns required static reference lists plus:

```json
{
  "dashboard_month": "2026-06",
  "current_month": "2026-07",
  "account_snapshot": {
    "status": "available",
    "selected_month": "2026-06",
    "source_month": "2026-05",
    "revision": 2,
    "carried_forward": true,
    "restated": true,
    "history_enabled": true,
    "tracking_started_month": "2026-05",
    "base_currency": "CNY",
    "timezone": "Asia/Shanghai",
    "accounts": []
  },
  "accounts": [],
  "transactions": []
}
```

Rules:

- `balance_snapshots` is omitted from the month projection, so three-second polling does not transfer all history or superseded revisions.
- `accounts` mirrors `account_snapshot.accounts`; it never contains present-day accounts for a historical request.
- `status: available` means a stored state resolved at or before the month. `carried_forward` identifies a quiet month and `source_month` preserves the real source.
- `status: unavailable` returns empty accounts and means no earlier trusted state exists. It is not zero net worth.
- Month validation accepts only real `YYYY-MM` values. Invalid values, including month 00 or 13, return HTTP 400.
- Ledger responses use `Cache-Control: no-store`.

### Unsupported static schema

`GET /api/book`, `GET /api/book?month=...`, `GET /api/months`, and `POST /api/analyze` return HTTP `409` with `error: unsupported_static_schema` for every static version other than integer `3`. Responses use `Cache-Control: no-store`; no current-account fallback, conversion, backup, or write occurs. `GET /api/analyze/status` remains available for status recovery because it does not consume ledger data.

### `GET /api/months`

Returns the sorted union of transaction-shard months, snapshot months, and the current natural month in the profile timezone:

```json
{
  "months": ["2026-05", "2026-06", "2026-07"],
  "current_month": "2026-07"
}
```

The endpoint inspects only valid `YYYY-MM.json` filename stems and static snapshot metadata; it does not read transaction bodies and does not write synthetic months. A listed filename is an available selector, not an assertion that its payload is valid; `/api/book?month=...` performs payload validation.

### `GET /api/analyze/status`

Preserves the existing `busy`, `started_at`, `elapsed_s`, and `window` fields and adds durable in-process outcome state for page reload and timeout/409 recovery:

```json
{
  "state": "succeeded",
  "run_id": "opaque-server-run-id",
  "busy": false,
  "started_at": 1783950000.0,
  "finished_at": 1783950030.0,
  "elapsed_s": 30.0,
  "window": "single month: 2026-07",
  "report_url": "/reports/analysis-2026-07.html",
  "error": null,
  "upstream_status": 200
}
```

`state` is `idle`, `running`, `succeeded`, or `failed`. A concurrent POST returns HTTP 409 plus the same current status under `analysis`. A stale running state becomes `failed` with `error.code: analysis_timeout`.

Each run writes to a private filename containing its run id. Only the still-current run may publish that private file to the stable report filename; an older timed-out worker is discarded and cannot overwrite a newer report or status. A newly published report backs up the previous stable report first. A run-specific error file takes precedence over any pre-existing successful report. Upstream failure, an error report, or a missing run-specific report persists a failed outcome.
