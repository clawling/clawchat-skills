# Monthly Analysis Report — workflow and output contract

Specification for the seven-section report produced when the user or dashboard requests an analysis of a personal-ledger window.

## Inputs

- `ACCOUNT_BOOK` (static profile/reference data plus monthly balance snapshots in `account-book.json`).
- `transactions/YYYY-MM.json` shards for the window and the prior comparable period.
- A natural-language brief stating the window, the comparison period, and any constraints (length, output format, sections).

The brief is the only instruction the user sees; everything in this file is internal.

## What the seven sections are and why

| § | Section | Source fields | One-line definition |
|---|---|---|---|
| 1 | Net worth snapshot | resolved `balance_snapshots[*].accounts`, captured base currency | Add active assets/receivables and subtract active liabilities only in the snapshot's base currency; list other currencies separately as unconverted. |
| 2 | Cash flow | `transactions[*].kind`, `amount_minor`, `base_amount_minor` | Income, expense, net, savings rate (`net / income`). |
| 3 | Category breakdown | `transactions[kind=expense].category` | Top 5 by amount, with prior-period delta and share %. |
| 4 | Budget progress | `budgets[*].category`, `limit_minor` vs `transactions[kind=expense]` | Spent vs limit, traffic light: 🔴 >95%, 🟡 ≥70%, 🟢 <70%. |
| 5 | Subscription audit | `subscriptions[*]`, `transactions[subscription_id]` | Per subscription: expected dates in window, observed charges, status emoji. |
| 6 | Anomalies & duplicates | All transactions in window + provenance availability | Single-txn outliers, duplicate suspects, and a truthful unavailable state for account drift when balance effects cannot be replayed. |
| 7 | Action recommendations | All of the above | Up to 5 highest-financial-impact items, with proposed next step. |

## Window-length shapes

- **Window length == 1 month**: skip the time-series SVG chart. Replace it with one bullet row per metric that a longer window would have plotted. Tables are sufficient. This avoids the "single dot" chart that adds no information.
  - Concrete replacement: under §1 "major income/expense inflection points", render a `<ul>` with one `<li>` per inflection transaction (date · kind · amount · account · title). Under §2, render the four metric cards (income, expense, net, savings rate) with no SVG. A sparkline with a single data point adds no information, and the skill contract forbids it.
- **Window length > 1 month**: include a cash-flow-over-time inline SVG sparkline (or a small monthly bar chart) of income vs expense per month in the window. Keep it monochrome and tabular, not a marketing graphic.
- **Window length > 12 months**: rolling-90-day average overlay; do not extend the table.

## Inflection-point threshold (5% of monthly income)

The 5%-of-monthly-income inflection rule is applied per single transaction. If a transaction's `base_amount_minor` absolute value is ≥ `0.05 × month_income`, list it under §1. When `month_income == 0` the threshold falls back to "any non-zero amount" and the listing is just the lone income/expense observed.

## Subscription status semantics

- `✅` — expected AND observed in window AND amount matches `subscriptions[*].amount_minor` in `subscriptions[*].currency`.
- `📅` — no expected billing date in window AND no observed charge (next billing is after window end).
- `⚠️` — observed charge without an expected date in window (early), OR expected date with no observed charge (missing).
- `❌` — amount or currency mismatch.

Always list both the expected date and the observed date, even when the status is `✅`, so the user can verify the cadence by eye.

## Account drift availability

Account drift is unavailable when balance-effect provenance is incomplete. Existing transactions do not persist whether `--no-balance-update` was used, and direct account replacements are not replayable events. Do not subtract transaction sums from a present or historical snapshot and label the difference an anomaly. Render a muted explanation that reconciliation requires complete balance-effect provenance.

## Outlier & duplicate thresholds

- Outlier: needs ≥ 2 samples in the same category inside the window. If a category has only 1 transaction, report "sample size is too small to calculate the 95th percentile" and skip. This is a deliberate fail-soft, not a bug.
- Duplicate suspect: 2 expense transactions within 7 days, same `account_id`, same `category`, with substring title overlap, and `|amount_a − amount_b| / max(amount_a, amount_b) ≤ 10%`. Report with both rows so the user can delete one or keep both. Never auto-delete.

## Currency treatment

For transaction cash flow, use `base_amount_minor` when its `base_currency` matches the report base currency. If it is missing, use only the transaction's linked rate or a persisted rate for the exact transaction date and pair. Otherwise keep the native amount, mark base-currency subtotals partial, and say conversion is unavailable. Never coerce an unavailable conversion to zero.

For account balances and net worth, never apply an exchange rate. Use only active accounts whose currency equals the resolved snapshot's captured base currency and list all other currencies separately as unconverted.

## Output file

- **Default path is set by the caller** via `REPORT_PATH` (or the liveware dashboard's own filename). Use it byte-for-byte; do not rename. The liveware dashboard in this environment writes to `<DATA_DIR>/reports/analysis-YYYY-MM.html`; the brief's "write to report-YYYY-MM.html" wording is a generic instruction, not a binding filename. Always honor `REPORT_PATH` first; fall back to `<DATA_DIR>/reports/analysis-YYYY-MM.html` only when no path is supplied.
- HTML only. Single self-contained file. No external CSS, no JS, no fonts. Use the `oklch` color tokens from the liveware dashboard for visual continuity.
- Use seven sections with one `<h2>` per section, plus one `<h1>`, one `<main>`, and one `<footer>`.
- Charts: only include inline `<svg>`. No `<img>` referencing external sources. No data URIs for fonts.

## User-facing translation guardrails

The `data-contract.md` already lists the banned terms. Reinforce for the report:

- Never quote `balance_minor`, `amount_minor`, `base_amount_minor`, `kind`, `account_id`, `subscription_id`, `exchange_rate_id`, `next_billing_date`, `metadata.updated_at`, `txn_*`, `acct_*`, `sub_*`, `budget_*`, `fx_*` ids, or `json`/`JSON` in the user-facing prose.
- Use "amount"/"cash flow"/"account"/"subscription"/"budget"/"CNY conversion" instead. Internal script lines can still print these values, but the rendered report text is the only thing the user sees.
- "Status" labels: 🔴/🟡/🟢 are fine; "red"/"amber"/"green" in CSS class names are fine internally. The user sees the emojis, not the class names.

## Backup convention

Before overwriting an existing report file, rename the old file to `<original-name>.<ISO-timestamp>.bak.html` (e.g., `analysis-2026-07.2026-07-08T06-11-53.bak.html` when the live filename is `analysis-2026-07.html`). Insert the timestamp BEFORE the final `.html` extension, do not append after it. Never silently overwrite. This protects iterations when the user asks to "regenerate" the report.

## Subscription expected-date algorithm

Use the most recent prior cycle. For each active subscription:

1. Compute `prior = next_billing_date − cadence_step`, where `cadence_step` is `weekly=7d, monthly=30d, quarterly=91d, yearly=365d`.
2. If `window_start ≤ prior ≤ window_end`, include `prior` as the expected billing date.
3. Only include a second prior cycle (`prior − cadence_step`) when `(window_end − window_start).days > cadence_step.days` — i.e. the window is wider than one cadence. For a 1-month window against a monthly cadence, exactly one expected date per subscription.

## Subscription early-charge status

The four-emoji matrix in the recipe is correct for clean cases but is ambiguous when an observed charge predates the expected date yet matches amount/currency. Treat it as:

- If the subscription's `source.review_reason == "early_subscription_charge"` (or the txn `notes` mention "earlier than expected date"), use the status emoji that matches the formal matrix (✅ if amount/currency match) BUT in §5's narrative line add a parenthetical: "(charged N days earlier than expected, needs review)" and surface the user-facing interpretation as a recommendation in §7. The matrix alone understates the financial concern; the recommendation is what makes it actionable.

**Detecting an early charge in practice.** The trigger fields listed above (`source.review_reason`, `txn.notes`) are *not* reliable in real ledgers — most user-entered subscriptions lack both, and the only universally present signal is the date arithmetic itself. The robust detection is purely computational: for each subscription, compute `days_early = expected_date - observed_date` (positive when observed is earlier). If `days_early > 0` AND the observed amount/currency match the subscription's stored `amount_minor`/`currency`, treat it as an "early charge". Render §5 with the formal-matrix emoji (✅ when amount/currency match) AND the parenthetical "charged N days earlier than expected, needs review" in the narrative, AND raise a §7 recommendation asking the owner to either confirm the cadence or flag the charge. Do not rely on the `source.review_reason` field as the sole trigger — it is too often empty, while the date delta is always derivable.

Treat the subscription review flag as a secondary hint only; use the expected-versus-observed date delta to determine whether a charge is early.

## Historical snapshot resolution

For each natural month:

1. Select snapshot rows with `month <= selected_month`.
2. Within each source month, choose the highest revision.
3. Choose the latest eligible source month.
4. Mark the result carried forward when its source month differs from the selected month.
5. If no eligible row exists, mark assets and net worth unavailable. Never carry a later row backward.

Month-over-month net-worth delta is available only when both resolved states exist and use the same captured base currency. Multi-month charts leave unavailable months as gaps and never interpolate.

## Thin-window fail-soft behavior

When the window contains ≤5 transactions, several anomaly subsections will legitimately be empty:

- Outliers: every category with 1 sample gets "sample size is too small to calculate the 95th percentile"; with 2 samples the p95 is just the max, so the rule is "only flag if strictly greater than max" (i.e. never).
- Duplicates: with ≤2 expenses in window, only same-day pairs can match the 7-day rule. A 0-result is the correct outcome, not a missed detection.
- Drift: report unavailable whenever balance-effect provenance is incomplete; sample size does not make an unprovable reconciliation valid.

Render these as "none" with a short muted explanation ("this month's sample size is too small to calculate the 95th percentile; skipped by rule"), never as "—" or blank cells. Empty-but-explained is friendlier than ambiguous-empty.

**§3 fail-soft: fewer than 5 expense categories.** The Top-5 spec means up to five real categories. When the window has fewer, render all available categories and explain that the shorter list reflects the recorded distribution. Do not invent or pad rows.

**§3 fail-soft: no prior baseline.** When a category has current spending but zero prior-period spending, render the delta as `new`, `new category`, or `no prior period`; never display `Infinity`, `inf`, or `∞`. Treat a large percentage change on a very small baseline as a warning rather than a positive trend.

**§3 data-source wording.** Use user-facing phrases such as "current-period ledger snapshot" and "prior-period transaction records". Do not expose storage filenames unless the user explicitly asks for technical details.

## What's not in scope

- Tax, investment, loan, or legal advice.
- Multi-currency revaluation. The report follows each resolved snapshot's captured base currency and leaves other account currencies unconverted.
- Forward projection (e.g., "at this rate you'll save X by year-end"). The window is historical.
- Cross-account reconciliation against bank statements. The ledger is the source of truth for the report; the user reconciles manually.

## Operator checklist before delivery

0. **Preflight**: count transactions in window. If ≤5, expect §6 to be mostly empty-with-explanation; this is correct, not a bug. Skip this check only if the user is comparing against a thick prior period and explicitly asked for stricter anomaly thresholds.
1. Open the static book, list transaction and snapshot months, pick the natural-month window and prior period, and resolve account snapshots without reverse carry.
2. Compute the seven sections in order. Verify the `<h2>` ordering matches the table at the top: Net Worth Snapshot → Cash Flow → Category Breakdown → Budget Progress → Subscription Audit → Anomalies & Duplicates → Action Recommendations.
3. Write the HTML to the path supplied by the caller (usually `REPORT_PATH`; default `<DATA_DIR>/reports/analysis-YYYY-MM.html`) with backup rename of the prior file.
4. `grep` the file for `<script`, `https?://`, `data-action` (operator dashboard only, never in the report), and the banned-term list from the user-facing translations block in `references/data-contract.md`. Reject if anything leaks. Two highest-yield manual sweeps beyond the regex: (a) every `delta` cell in §3 — confirm none of them are literally `Infinity` / `inf` / `∞`; (b) the footer "data source" line — confirm no `.json` / `account-book` / `transactions/` strings.
5. Verify exactly one `<h1>`, one `<main>`, seven `<section>` with seven `<h2>` in the right order, one `<footer>`. If the window is 1 month, no inline SVG is required; if longer, the SVG must be inline.
6. Return a one-line summary in chat: the report path, the seven section headers (or 1–2 of the most surprising findings), and a friendly "let me know if you'd like adjustments". Do not paste the full report.
