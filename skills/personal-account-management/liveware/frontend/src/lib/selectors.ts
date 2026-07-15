import type {
  Account,
  AccountDisplayGroup,
  AccountDisplayRow,
  AccountSummary,
  BookResponse,
  BudgetProgress,
  CashFlowSummary,
  ControllerFilters,
  NativeCashFlowGroup,
  NaturalWeekBucket,
  SubscriptionSummary,
  Transaction,
  TransactionPage,
} from "./types.js";

function upper(value: string | null | undefined, fallback = ""): string {
  return (value || fallback).toUpperCase();
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function signedAccountBalance(account: Account): number {
  return account.type === "liability"
    ? -Math.abs(account.balance_minor)
    : account.balance_minor;
}

function transactionAmountInCurrency(
  transaction: Transaction,
  targetCurrency: string,
): number | null {
  const target = upper(targetCurrency);
  if (
    isInteger(transaction.base_amount_minor)
    && upper(transaction.base_currency) === target
  ) {
    return transaction.base_amount_minor;
  }
  if (upper(transaction.currency) === target && isInteger(transaction.amount_minor)) {
    return transaction.amount_minor;
  }
  return null;
}

export function summarizeAccounts(book: BookResponse): AccountSummary {
  const snapshot = book.account_snapshot;
  const baseCurrency = upper(snapshot.base_currency, book.profile.base_currency || "CNY");
  if (snapshot.status === "unavailable") {
    return {
      available: false,
      base_currency: baseCurrency,
      base_net_worth_minor: null,
      base_assets_minor: 0,
      base_liabilities_minor: 0,
      base_receivables_minor: 0,
      groups: [],
      foreign_balances: [],
    };
  }

  let baseAssets = 0;
  let baseLiabilities = 0;
  let baseReceivables = 0;
  const grouped = new Map<string, AccountDisplayRow[]>();
  const foreign = new Map<string, { balance: number; count: number }>();

  for (const account of snapshot.accounts) {
    if (account.active === false || !isInteger(account.balance_minor)) continue;
    const currency = upper(account.currency, baseCurrency);
    const signed = signedAccountBalance(account);
    const groupName = account.display_group || account.type || "Accounts";
    const group = grouped.get(groupName) ?? [];
    group.push({ ...account, currency, signed_balance_minor: signed });
    grouped.set(groupName, group);

    if (currency !== baseCurrency) {
      const row = foreign.get(currency) ?? { balance: 0, count: 0 };
      row.balance += signed;
      row.count += 1;
      foreign.set(currency, row);
      continue;
    }
    if (account.type === "liability") {
      baseLiabilities += Math.abs(account.balance_minor);
    } else if (account.type === "receivable") {
      baseReceivables += account.balance_minor;
    } else {
      baseAssets += account.balance_minor;
    }
  }

  const groups: AccountDisplayGroup[] = [...grouped.entries()].map(([name, accounts]) => ({
    name,
    accounts,
  }));
  return {
    available: true,
    base_currency: baseCurrency,
    base_net_worth_minor: baseAssets + baseReceivables - baseLiabilities,
    base_assets_minor: baseAssets,
    base_liabilities_minor: baseLiabilities,
    base_receivables_minor: baseReceivables,
    groups,
    foreign_balances: [...foreign.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([currency, row]) => ({
        currency,
        balance_minor: row.balance,
        account_count: row.count,
      })),
  };
}

export function summarizeCashFlow(book: BookResponse): CashFlowSummary {
  const baseCurrency = upper(book.account_snapshot.base_currency, book.profile.base_currency || "CNY");
  let income = 0;
  let expense = 0;
  const unconverted = new Map<string, NativeCashFlowGroup>();

  for (const transaction of book.transactions) {
    if (transaction.kind !== "income" && transaction.kind !== "expense") continue;
    const amount = transactionAmountInCurrency(transaction, baseCurrency);
    if (amount !== null) {
      if (transaction.kind === "income") income += amount;
      else expense += amount;
      continue;
    }
    const currency = upper(transaction.currency, baseCurrency);
    const row = unconverted.get(currency) ?? {
      currency,
      income_minor: 0,
      expense_minor: 0,
      transaction_count: 0,
    };
    if (transaction.kind === "income") row.income_minor += transaction.amount_minor;
    else row.expense_minor += transaction.amount_minor;
    row.transaction_count += 1;
    unconverted.set(currency, row);
  }

  return {
    base_currency: baseCurrency,
    income_minor: income,
    expense_minor: expense,
    net_minor: income - expense,
    conversion_complete: unconverted.size === 0,
    unconverted: [...unconverted.values()].sort((a, b) => a.currency.localeCompare(b.currency)),
  };
}

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function addUtcDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setUTCDate(next.getUTCDate() + days);
  return next;
}

function monthBounds(month: string): { start: Date; end: Date } {
  const match = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(month);
  if (!match) throw new Error(`Invalid natural month: ${month}`);
  const year = Number(match[1]);
  const monthIndex = Number(match[2]) - 1;
  return {
    start: new Date(Date.UTC(year, monthIndex, 1)),
    end: new Date(Date.UTC(year, monthIndex + 1, 0)),
  };
}

export function buildNaturalWeekBuckets(book: BookResponse): NaturalWeekBucket[] {
  const { start, end } = monthBounds(book.dashboard_month);
  const baseCurrency = upper(book.account_snapshot.base_currency, book.profile.base_currency || "CNY");
  const buckets: NaturalWeekBucket[] = [];
  let cursor = start;

  while (cursor <= end) {
    const daysToSunday = (7 - cursor.getUTCDay()) % 7;
    const possibleEnd = addUtcDays(cursor, daysToSunday);
    const bucketEnd = possibleEnd > end ? end : possibleEnd;
    buckets.push({
      start_date: isoDate(cursor),
      end_date: isoDate(bucketEnd),
      income_minor: 0,
      expense_minor: 0,
      net_minor: 0,
      has_activity: false,
      conversion_complete: true,
    });
    cursor = addUtcDays(bucketEnd, 1);
  }

  for (const transaction of book.transactions) {
    if (transaction.kind !== "income" && transaction.kind !== "expense") continue;
    if (!/^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.test(transaction.date)) continue;
    const bucket = buckets.find(
      (candidate) => transaction.date >= candidate.start_date && transaction.date <= candidate.end_date,
    );
    if (!bucket) continue;
    bucket.has_activity = true;
    const amount = transactionAmountInCurrency(transaction, baseCurrency);
    if (amount === null) {
      bucket.conversion_complete = false;
    } else if (transaction.kind === "income") {
      bucket.income_minor += amount;
    } else {
      bucket.expense_minor += amount;
    }
    bucket.net_minor = bucket.income_minor - bucket.expense_minor;
  }
  return buckets;
}

export function buildBudgetProgress(book: BookResponse): BudgetProgress[] {
  const fallbackCurrency = upper(book.account_snapshot.base_currency, book.profile.base_currency || "CNY");
  return book.budgets
    .filter((budget) => budget.active !== false && (budget.period ?? "monthly") === "monthly")
    .map((budget) => {
      const currency = upper(budget.currency, fallbackCurrency);
      let spent = 0;
      let conversionComplete = true;
      const nativeSpending = new Map<string, { expense: number; count: number }>();
      for (const transaction of book.transactions) {
        if (transaction.kind !== "expense" || transaction.category !== budget.category) continue;
        const amount = transactionAmountInCurrency(transaction, currency);
        if (amount === null) {
          conversionComplete = false;
          const nativeCurrency = upper(transaction.currency, currency);
          const native = nativeSpending.get(nativeCurrency) ?? { expense: 0, count: 0 };
          native.expense += transaction.amount_minor;
          native.count += 1;
          nativeSpending.set(nativeCurrency, native);
        } else {
          spent += amount;
        }
      }
      const ratio = budget.limit_minor > 0 ? spent / budget.limit_minor : 0;
      return {
        id: budget.id || `${budget.name}:${budget.category}`,
        name: budget.name,
        group: budget.group || "",
        category: budget.category,
        currency,
        limit_minor: budget.limit_minor,
        spent_minor: spent,
        ratio,
        status: !conversionComplete ? "partial" : ratio > 1 ? "over" : ratio >= 0.7 ? "watch" : "ok",
        conversion_complete: conversionComplete,
        native_spending: [...nativeSpending.entries()]
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([nativeCurrency, row]) => ({
            currency: nativeCurrency,
            expense_minor: row.expense,
            transaction_count: row.count,
          })),
      };
    });
}

export function selectTransactions(
  book: BookResponse,
  filters: ControllerFilters,
): TransactionPage {
  const query = filters.search.trim().toLocaleLowerCase();
  const accountNames = new Map(
    book.account_snapshot.accounts.map((account) => [account.id, account.name]),
  );
  const filtered = book.transactions
    .filter((transaction) => (
      filters.kind === "all"
      || (filters.kind === "review" ? transaction.needs_review === true : transaction.kind === filters.kind)
    ))
    .filter(
      (transaction) => !filters.accountId
        || transaction.account_id === filters.accountId
        || transaction.to_account_id === filters.accountId,
    )
    .filter((transaction) => {
      if (!query) return true;
      const searchable = [
        transaction.title,
        transaction.merchant,
        transaction.category,
        transaction.notes,
        ...(transaction.tags ?? []),
        transaction.account_id ? accountNames.get(transaction.account_id) : "",
        transaction.to_account_id ? accountNames.get(transaction.to_account_id) : "",
      ]
        .filter((value): value is string => typeof value === "string" && value.length > 0)
        .join("\n")
        .toLocaleLowerCase();
      return searchable.includes(query);
    })
    .sort((left, right) => {
      const dateOrder = right.date.localeCompare(left.date);
      if (dateOrder !== 0) return dateOrder;
      return String(right.created_at || right.id).localeCompare(String(left.created_at || left.id));
    });

  const pageSize = Math.max(1, Math.trunc(filters.pageSize));
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const page = Math.min(totalPages, Math.max(1, Math.trunc(filters.page)));
  const start = (page - 1) * pageSize;
  return {
    items: filtered.slice(start, start + pageSize),
    page,
    page_size: pageSize,
    total_items: filtered.length,
    total_pages: totalPages,
    source_items: book.transactions.length,
  };
}

function parseUtcDate(value: string): Date | null {
  const match = /^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.exec(value);
  if (!match) return null;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return isoDate(date) === value ? date : null;
}

function advanceOccurrence(value: Date, cadence: string): Date {
  if (cadence === "weekly") return addUtcDays(value, 7);
  const months = cadence === "yearly" ? 12 : cadence === "quarterly" ? 3 : 1;
  const firstOfTarget = new Date(Date.UTC(
    value.getUTCFullYear(),
    value.getUTCMonth() + months,
    1,
  ));
  const targetYear = firstOfTarget.getUTCFullYear();
  const targetMonth = firstOfTarget.getUTCMonth();
  const endOfMonth = new Date(Date.UTC(targetYear, targetMonth + 1, 0)).getUTCDate();
  return new Date(Date.UTC(
    targetYear,
    targetMonth,
    Math.min(value.getUTCDate(), endOfMonth),
  ));
}

function jumpStableOccurrences(value: Date, cadence: string, count: number): Date {
  if (cadence === "weekly") return addUtcDays(value, count * 7);
  const cadenceMonths = cadence === "yearly" ? 12 : cadence === "quarterly" ? 3 : 1;
  return new Date(Date.UTC(
    value.getUTCFullYear(),
    value.getUTCMonth() + count * cadenceMonths,
    value.getUTCDate(),
  ));
}

function expectedSubscriptionDates(
  nextBillingDate: string,
  cadence: string,
  month: string,
): string[] {
  const anchor = parseUtcDate(nextBillingDate);
  if (!anchor) return [];
  const { start, end } = monthBounds(month);
  if (cadence === "custom") {
    return anchor >= start && anchor <= end ? [isoDate(anchor)] : [];
  }
  if (anchor > end) return [];

  let candidate = anchor;
  if (cadence === "weekly" && candidate < start) {
    const elapsedWeeks = Math.floor(
      (start.getTime() - candidate.getTime()) / (7 * 86_400_000),
    );
    candidate = jumpStableOccurrences(candidate, cadence, Math.max(0, elapsedWeeks - 1));
  } else {
    // Repeated Python-style month clamping stabilizes within this short calendar window.
    for (let index = 0; index < 16 && candidate < start; index += 1) {
      candidate = advanceOccurrence(candidate, cadence);
    }
    if (candidate < start) {
      const cadenceMonths = cadence === "yearly" ? 12 : cadence === "quarterly" ? 3 : 1;
      const monthDistance = (
        (start.getUTCFullYear() - candidate.getUTCFullYear()) * 12
        + start.getUTCMonth()
        - candidate.getUTCMonth()
      );
      const skipped = Math.max(0, Math.floor(monthDistance / cadenceMonths) - 1);
      candidate = jumpStableOccurrences(candidate, cadence, skipped);
    }
  }
  while (candidate < start) candidate = advanceOccurrence(candidate, cadence);

  const dates: string[] = [];
  while (candidate <= end) {
    dates.push(isoDate(candidate));
    const next = advanceOccurrence(candidate, cadence);
    if (next <= candidate) break;
    candidate = next;
  }
  return dates;
}

function persistedExpectedDate(transaction: Transaction): string | null {
  const value = transaction.source?.expected_billing_date;
  return typeof value === "string" && parseUtcDate(value) ? value : null;
}

export function summarizeSubscriptions(book: BookResponse): SubscriptionSummary {
  const totals = new Map<string, {
    expected: number;
    observed: number;
    subscriptionIds: Set<string>;
  }>();
  const addTotal = (
    bucket: "expected" | "observed",
    currency: string,
    amount: number,
    subscriptionId: string,
  ): void => {
    if (!isInteger(amount) || amount <= 0) return;
    const total = totals.get(currency) ?? {
      expected: 0,
      observed: 0,
      subscriptionIds: new Set<string>(),
    };
    total[bucket] += amount;
    total.subscriptionIds.add(subscriptionId);
    totals.set(currency, total);
  };
  const observedSubscriptionIds = new Set(
    book.transactions
      .filter((transaction) => transaction.kind === "expense" && transaction.subscription_id)
      .map((transaction) => transaction.subscription_id),
  );
  const rows = book.subscriptions
    .filter((subscription) => (
      subscription.active !== false || observedSubscriptionIds.has(subscription.id)
    ))
    .map((subscription) => {
      const currency = upper(subscription.currency, book.profile.base_currency || "CNY");
      const observed = book.transactions.filter(
        (transaction) => transaction.kind === "expense"
          && transaction.subscription_id === subscription.id,
      );
      const expectedDates = [...new Set([
        ...expectedSubscriptionDates(
          subscription.next_billing_date,
          subscription.cadence || "monthly",
          book.dashboard_month,
        ),
        ...observed
          .map((transaction) => persistedExpectedDate(transaction))
          .filter((value): value is string => value?.startsWith(`${book.dashboard_month}-`) === true),
      ])].sort();
      const remainingExpectedDates = [...expectedDates];
      let matchedObservedCount = 0;
      observed.forEach((transaction) => {
        const persistedDate = persistedExpectedDate(transaction);
        const matchIndex = persistedDate
          ? remainingExpectedDates.indexOf(persistedDate)
          : -1;
        if (matchIndex >= 0) {
          remainingExpectedDates.splice(matchIndex, 1);
          matchedObservedCount += 1;
        }
        addTotal(
          "observed",
          upper(transaction.currency, currency),
          transaction.amount_minor,
          subscription.id,
        );
      });
      if (remainingExpectedDates.length > 0) {
        addTotal(
          "expected",
          currency,
          remainingExpectedDates.length * subscription.amount_minor,
          subscription.id,
        );
      }
      const observedMatches = observed.every(
        (transaction) => upper(transaction.currency) === currency
          && transaction.amount_minor === subscription.amount_minor,
      );
      let status: "observed" | "expected" | "not_due" | "unexpected" | "mismatch";
      if (observed.length > matchedObservedCount) status = "unexpected";
      else if (observed.length > 0 && !observedMatches) status = "mismatch";
      else if (remainingExpectedDates.length > 0) status = "expected";
      else if (observed.length > 0) status = "observed";
      else if (expectedDates.length > 0) status = "expected";
      else status = "not_due";
      return {
        id: subscription.id,
        name: subscription.name,
        description: subscription.description || "",
        amount_minor: subscription.amount_minor,
        currency,
        cadence: subscription.cadence,
        next_billing_date: subscription.next_billing_date,
        payment_account_id: subscription.payment_account_id || "",
        expected_dates: expectedDates,
        observed_count: observed.length,
        observed_charges: observed.map((transaction) => ({
          id: transaction.id,
          date: transaction.date,
          amount_minor: transaction.amount_minor,
          currency: upper(transaction.currency, currency),
        })),
        status,
      };
    })
    .sort((left, right) => {
      const dueOrder = Number(right.expected_dates.length > 0) - Number(left.expected_dates.length > 0);
      if (dueOrder !== 0) return dueOrder;
      return left.name.localeCompare(right.name);
    });

  return {
    rows,
    totals: [...totals.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([currency, total]) => ({
        currency,
        expected_minor: total.expected,
        observed_minor: total.observed,
        subscription_count: total.subscriptionIds.size,
      })),
  };
}
