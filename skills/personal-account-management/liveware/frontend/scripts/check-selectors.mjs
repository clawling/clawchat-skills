import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputDir = await mkdtemp(path.join(tmpdir(), "pam-selector-check-"));

try {
  await writeFile(path.join(outputDir, "package.json"), '{"type":"module"}\n');
  const tsc = path.join(frontendDir, "node_modules", "typescript", "bin", "tsc");
  const compile = spawnSync(
    process.execPath,
    [
      tsc,
      "src/lib/selectors.ts",
      "src/lib/types.ts",
      "src/lib/request-ownership.ts",
      "--module", "NodeNext",
      "--moduleResolution", "NodeNext",
      "--target", "ES2022",
      "--outDir", outputDir,
      "--rootDir", "src/lib",
      "--skipLibCheck",
    ],
    { cwd: frontendDir, encoding: "utf8" },
  );
  if (compile.status !== 0) {
    process.stderr.write(compile.stdout ?? "");
    process.stderr.write(compile.stderr ?? "");
    throw new Error(`selector compilation failed with status ${compile.status}`);
  }

  const {
    buildBudgetProgress,
    buildNaturalWeekBuckets,
    selectTransactions,
    summarizeAccounts,
    summarizeCashFlow,
    summarizeSubscriptions,
  } = await import(`${pathToFileURL(path.join(outputDir, "selectors.js")).href}?v=${Date.now()}`);
  const {
    analysisRecoveryOwnsLifecycle,
    analysisStatusCanPublish,
    analysisStatusFromPayload,
    dashboardLoadErrorFrom,
    refreshFailureShouldPublish,
    requestOwnsSelection,
  } = await import(
    `${pathToFileURL(path.join(outputDir, "request-ownership.js")).href}?v=${Date.now()}`
  );
  assert.equal(requestOwnsSelection(4, "2026-08", 4, "2026-08"), true);
  assert.equal(requestOwnsSelection(5, "2026-09", 4, "2026-08"), false);
  assert.equal(requestOwnsSelection(4, "2026-09", 4, "2026-08"), false);
  assert.equal(dashboardLoadErrorFrom("unsupported_static_schema"), "unsupported");
  assert.equal(dashboardLoadErrorFrom("invalid_static_ledger"), "invalid");
  assert.equal(dashboardLoadErrorFrom("unexpected"), "unavailable");
  assert.equal(dashboardLoadErrorFrom(null), "unavailable");
  assert.equal(refreshFailureShouldPublish(false, false), true);
  assert.equal(refreshFailureShouldPublish(true, false), false);
  assert.equal(refreshFailureShouldPublish(true, true), true);
  assert.equal(analysisRecoveryOwnsLifecycle(true, 4, 4), true);
  assert.equal(analysisRecoveryOwnsLifecycle(false, 4, 4), false);
  assert.equal(analysisRecoveryOwnsLifecycle(true, 5, 4), false);
  const analysisStatus = (state, runId, busy = state === "running", startedAt = 1) => ({
    state, run_id: runId, busy, started_at: startedAt, finished_at: 0,
    elapsed_s: 1, window: "single month: 2026-07", report_url: null,
    error: null, upstream_status: null,
  });
  const runningAnalysis = analysisStatus("running", "run-1");
  const finishedAnalysis = analysisStatus("succeeded", "run-1", false);
  const localFailure = analysisStatus("failed", "", false);
  assert.deepEqual(analysisStatusFromPayload({ analysis: runningAnalysis }), runningAnalysis);
  assert.equal(analysisStatusFromPayload({ state: "unknown" }), null);
  assert.equal(analysisStatusCanPublish(finishedAnalysis, runningAnalysis, 2, 2), false);
  assert.equal(analysisStatusCanPublish(localFailure, analysisStatus("idle", "", false, 0), 2, 2), false);
  assert.equal(analysisStatusCanPublish(localFailure, runningAnalysis, 2, 2), true);
  assert.equal(analysisStatusCanPublish(finishedAnalysis, analysisStatus("idle", "", false, 0), 2, 2), false);
  assert.equal(analysisStatusCanPublish(finishedAnalysis, analysisStatus("failed", "run-1", false), 2, 2), false);
  assert.equal(analysisStatusCanPublish(finishedAnalysis, analysisStatus("running", "run-old", true, 0), 2, 2), false);
  assert.equal(analysisStatusCanPublish(finishedAnalysis, analysisStatus("running", "run-new", true, 2), 2, 2), true);
  assert.equal(analysisStatusCanPublish(runningAnalysis, finishedAnalysis, 3, 2), false);

  const account = (id, type, currency, balance) => ({
    id,
    name: id,
    type,
    currency,
    balance_minor: balance,
    active: true,
  });
  const book = {
    schema_version: 3,
    dashboard_month: "2026-07",
    current_month: "2026-07",
    profile: { base_currency: "CNY", timezone: "Asia/Shanghai" },
    account_snapshot: {
      status: "available",
      selected_month: "2026-07",
      source_month: "2026-07",
      revision: 1,
      created_at: null,
      updated_at: null,
      capture_type: "automatic",
      reason: "",
      carried_forward: false,
      restated: false,
      history_enabled: true,
      tracking_started_month: "2026-07",
      base_currency: "CNY",
      timezone: "Asia/Shanghai",
      accounts: [
        account("cash", "asset", "CNY", 10_000),
        account("debt", "liability", "CNY", 2_000),
        account("usd", "asset", "USD", 5_000),
      ],
    },
    accounts: [],
    categories: [],
    budgets: [{
      id: "travel-budget",
      name: "Travel",
      group: "Plans",
      category: "Travel",
      period: "monthly",
      limit_minor: 1_000,
      currency: "CNY",
      active: true,
    }],
    transactions: [
      { id: "base-expense", date: "2026-07-01", kind: "expense", title: "Rail", merchant: "Metro", category: "Travel", account_id: "cash", subscription_id: "gym", tags: ["commute"], needs_review: true, amount_minor: 100, currency: "CNY", source: { expected_billing_date: "2026-07-01" } },
      { id: "native-expense", date: "2026-07-02", kind: "expense", title: "Hotel", category: "Travel", account_id: "usd", amount_minor: 500, currency: "USD", base_amount_minor: null, base_currency: null },
      { id: "income", date: "2026-07-07", kind: "income", title: "Pay", category: "Income", account_id: "cash", amount_minor: 1_000, currency: "CNY" },
      { id: "native-only-week", date: "2026-07-15", kind: "expense", title: "Museum", category: "Leisure", account_id: "usd", amount_minor: 500, currency: "USD" },
    ],
    subscriptions: [
      { id: "gym", name: "Gym", amount_minor: 100, currency: "CNY", cadence: "monthly", next_billing_date: "2026-07-01", payment_account_id: "cash", active: true },
      { id: "codex", name: "Codex", amount_minor: 2_000, currency: "USD", cadence: "monthly", next_billing_date: "2026-07-20", payment_account_id: "usd", active: true },
      { id: "annual", name: "Annual", amount_minor: 5_000, currency: "CNY", cadence: "yearly", next_billing_date: "2026-12-10", payment_account_id: "cash", active: true },
      { id: "custom", name: "Custom", amount_minor: 300, currency: "CNY", cadence: "custom", next_billing_date: "2026-07-10", payment_account_id: "cash", active: true },
      { id: "weekly", name: "Weekly", amount_minor: 50, currency: "USD", cadence: "weekly", next_billing_date: "2026-07-03", payment_account_id: "usd", active: true },
      { id: "mismatch", name: "Mismatch", amount_minor: 1_000, currency: "USD", cadence: "monthly", next_billing_date: "2026-07-08", payment_account_id: "usd", active: true },
    ],
    exchange_rates: [{ id: "ignored", date: "2026-07-02", from: "USD", to: "CNY", rate: 99 }],
    metadata: {},
  };

  const accounts = summarizeAccounts(book);
  assert.equal(accounts.base_net_worth_minor, 8_000);
  assert.deepEqual(accounts.foreign_balances, [{ currency: "USD", balance_minor: 5_000, account_count: 1 }]);

  const cashFlow = summarizeCashFlow(book);
  assert.equal(cashFlow.income_minor, 1_000);
  assert.equal(cashFlow.expense_minor, 100);
  assert.equal(cashFlow.conversion_complete, false);
  assert.equal(cashFlow.unconverted[0].currency, "USD");
  assert.equal(cashFlow.unconverted[0].expense_minor, 1_000);

  const weeks = buildNaturalWeekBuckets(book);
  assert.deepEqual(
    weeks.slice(0, 2).map((week) => [week.start_date, week.end_date]),
    [["2026-07-01", "2026-07-05"], ["2026-07-06", "2026-07-12"]],
  );
  assert.equal(weeks[0].has_activity, true);
  assert.equal(weeks[0].conversion_complete, false);
  assert.equal(weeks[2].has_activity, true);
  assert.equal(weeks[2].income_minor, 0);
  assert.equal(weeks[2].expense_minor, 0);
  assert.equal(weeks[2].conversion_complete, false);

  const budget = buildBudgetProgress(book)[0];
  assert.equal(budget.group, "Plans");
  assert.equal(budget.status, "partial");
  assert.equal(budget.spent_minor, 100);
  assert.deepEqual(budget.native_spending, [{ currency: "USD", expense_minor: 500, transaction_count: 1 }]);

  const unavailable = summarizeAccounts({
    ...book,
    account_snapshot: { ...book.account_snapshot, status: "unavailable", accounts: [] },
  });
  assert.equal(unavailable.base_net_worth_minor, null);
  assert.deepEqual(unavailable.groups, []);

  const searched = selectTransactions(book, {
    search: "metro",
    kind: "all",
    accountId: "",
    page: 1,
    pageSize: 20,
  });
  assert.deepEqual(searched.items.map((transaction) => transaction.id), ["base-expense"]);
  const reviewOnly = selectTransactions(book, {
    search: "", kind: "review", accountId: "", page: 1, pageSize: 20,
  });
  assert.deepEqual(reviewOnly.items.map((transaction) => transaction.id), ["base-expense"]);
  const filteredPage = selectTransactions(book, {
    search: "",
    kind: "expense",
    accountId: "usd",
    page: 2,
    pageSize: 1,
  });
  assert.equal(filteredPage.total_items, 2);
  assert.equal(filteredPage.total_pages, 2);
  assert.equal(filteredPage.page, 2);

  const subscriptions = summarizeSubscriptions(book);
  assert.equal(subscriptions.rows.find((row) => row.id === "gym").status, "observed");
  assert.equal(subscriptions.rows.find((row) => row.id === "codex").status, "expected");
  assert.equal(subscriptions.rows.find((row) => row.id === "annual").status, "not_due");
  assert.deepEqual(subscriptions.rows.find((row) => row.id === "custom").expected_dates, ["2026-07-10"]);
  assert.deepEqual(
    subscriptions.rows.find((row) => row.id === "weekly").expected_dates,
    ["2026-07-03", "2026-07-10", "2026-07-17", "2026-07-24", "2026-07-31"],
  );
  assert.deepEqual(subscriptions.totals, [
    { currency: "CNY", expected_minor: 300, observed_minor: 100, subscription_count: 2 },
    { currency: "USD", expected_minor: 3_250, observed_minor: 0, subscription_count: 3 },
  ]);

  const activityBook = {
    ...book,
    transactions: [
      ...book.transactions,
      { id: "unexpected-annual", date: "2026-07-09", kind: "expense", title: "Annual", category: "Subscriptions", account_id: "cash", subscription_id: "annual", amount_minor: 5_000, currency: "CNY" },
      { id: "mismatch-charge", date: "2026-07-08", kind: "expense", title: "Mismatch", category: "Subscriptions", account_id: "usd", subscription_id: "mismatch", amount_minor: 900, currency: "EUR", source: { expected_billing_date: "2026-07-08" } },
      { id: "weekly-charge", date: "2026-07-03", kind: "expense", title: "Weekly", category: "Subscriptions", account_id: "usd", subscription_id: "weekly", amount_minor: 50, currency: "USD", source: { expected_billing_date: "2026-07-03" } },
      { id: "not-a-charge", date: "2026-07-12", kind: "income", title: "Refund", category: "Income", account_id: "usd", subscription_id: "codex", amount_minor: 9_999, currency: "USD" },
    ],
  };
  const activitySubscriptions = summarizeSubscriptions(activityBook);
  assert.equal(activitySubscriptions.rows.find((row) => row.id === "annual").status, "unexpected");
  assert.equal(activitySubscriptions.rows.find((row) => row.id === "mismatch").status, "mismatch");
  assert.equal(activitySubscriptions.rows.find((row) => row.id === "codex").status, "expected");
  assert.equal(activitySubscriptions.rows.find((row) => row.id === "weekly").status, "expected");
  assert.equal(activitySubscriptions.rows.find((row) => row.id === "weekly").observed_count, 1);
  assert.deepEqual(activitySubscriptions.totals, [
    { currency: "CNY", expected_minor: 300, observed_minor: 5_100, subscription_count: 3 },
    { currency: "EUR", expected_minor: 0, observed_minor: 900, subscription_count: 1 },
    { currency: "USD", expected_minor: 2_200, observed_minor: 50, subscription_count: 2 },
  ]);

  const augustSubscriptions = summarizeSubscriptions({ ...book, dashboard_month: "2026-08", transactions: [] });
  assert.equal(augustSubscriptions.rows.find((row) => row.id === "custom").status, "not_due");
  const monthEndSubscriptions = summarizeSubscriptions({
    ...book,
    dashboard_month: "2027-02",
    transactions: [],
    subscriptions: [{ id: "month-end", name: "Month end", amount_minor: 100, currency: "CNY", cadence: "monthly", next_billing_date: "2026-07-31", payment_account_id: "cash", active: true }],
  });
  assert.deepEqual(monthEndSubscriptions.rows[0].expected_dates, ["2027-02-28"]);
  const driftedMonthEnd = summarizeSubscriptions({
    ...book,
    dashboard_month: "2027-03",
    transactions: [],
    subscriptions: [{ id: "month-end", name: "Month end", amount_minor: 100, currency: "CNY", cadence: "monthly", next_billing_date: "2026-07-31", active: true }],
  });
  assert.deepEqual(driftedMonthEnd.rows[0].expected_dates, ["2027-03-28"]);
  const quarterlyClamp = summarizeSubscriptions({
    ...book,
    dashboard_month: "2026-07",
    transactions: [],
    subscriptions: [{ id: "quarter-end", name: "Quarter end", amount_minor: 100, currency: "CNY", cadence: "quarterly", next_billing_date: "2026-01-31", active: true }],
  });
  assert.deepEqual(quarterlyClamp.rows[0].expected_dates, ["2026-07-30"]);
  const staleWeekly = summarizeSubscriptions({
    ...book,
    transactions: [],
    subscriptions: [{ id: "stale-weekly", name: "Stale weekly", amount_minor: 10, currency: "CNY", cadence: "weekly", next_billing_date: "2020-01-03", active: true }],
  });
  assert.deepEqual(
    staleWeekly.rows[0].expected_dates,
    ["2026-07-03", "2026-07-10", "2026-07-17", "2026-07-24", "2026-07-31"],
  );

  const recordedSchedule = summarizeSubscriptions({
    ...book,
    transactions: [
      { id: "recorded-month-end", date: "2026-07-31", kind: "expense", title: "Month end", category: "Subscriptions", subscription_id: "month-end", amount_minor: 100, currency: "CNY", source: { expected_billing_date: "2026-07-31" } },
      { id: "recorded-custom", date: "2026-07-10", kind: "expense", title: "Custom", category: "Subscriptions", subscription_id: "custom-next", amount_minor: 300, currency: "CNY", source: { expected_billing_date: "2026-07-10" } },
    ],
    subscriptions: [
      { id: "month-end", name: "Month end", amount_minor: 100, currency: "CNY", cadence: "monthly", next_billing_date: "2026-08-31", active: true },
      { id: "custom-next", name: "Custom next", amount_minor: 300, currency: "CNY", cadence: "custom", next_billing_date: "2026-09-10", active: true },
    ],
  });
  assert.deepEqual(recordedSchedule.rows.find((row) => row.id === "month-end").expected_dates, ["2026-07-31"]);
  assert.equal(recordedSchedule.rows.find((row) => row.id === "month-end").status, "observed");
  assert.deepEqual(recordedSchedule.rows.find((row) => row.id === "custom-next").expected_dates, ["2026-07-10"]);
  assert.equal(recordedSchedule.rows.find((row) => row.id === "custom-next").status, "observed");

  const inactiveHistorical = summarizeSubscriptions({
    ...book,
    subscriptions: [{ id: "retired", name: "Retired label", amount_minor: 700, currency: "JPY", cadence: "monthly", next_billing_date: "2026-08-01", active: false }],
    transactions: [{ id: "retired-charge", date: "2026-07-01", kind: "expense", title: "Retired label", category: "Subscriptions", subscription_id: "retired", amount_minor: 700, currency: "JPY", source: { expected_billing_date: "2026-07-01" } }],
  });
  assert.equal(inactiveHistorical.rows[0].name, "Retired label");
  assert.equal(inactiveHistorical.rows[0].status, "observed");

  const unprovenCharge = summarizeSubscriptions({
    ...book,
    subscriptions: [{ id: "proof-required", name: "Proof required", amount_minor: 2_000, currency: "USD", cadence: "monthly", next_billing_date: "2026-07-20", active: true }],
    transactions: [{ id: "missing-proof", date: "2026-07-20", kind: "expense", title: "Proof required", category: "Subscriptions", subscription_id: "proof-required", amount_minor: 1_900, currency: "USD" }],
  });
  assert.equal(unprovenCharge.rows[0].status, "unexpected");
  assert.deepEqual(unprovenCharge.totals, [
    { currency: "USD", expected_minor: 2_000, observed_minor: 1_900, subscription_count: 1 },
  ]);

  console.log("selector behavior is correct");
} finally {
  await rm(outputDir, { recursive: true, force: true });
}
