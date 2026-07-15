export type AnalysisState = "idle" | "running" | "succeeded" | "failed";
export type AccountType = "asset" | "liability" | "receivable" | string;
export type TransactionKind = "income" | "expense" | "transfer";
export type SnapshotStatus = "available" | "unavailable";
export type Language = "en" | "zh";
export type DashboardLoadError = "unsupported" | "invalid" | "unavailable";
export type DashboardSection = "overview" | "transactions" | "subscriptions" | "analysis";
export type KindFilter = "all" | "review" | TransactionKind;

export interface LedgerProfile {
  owner_name?: string;
  base_currency: string;
  timezone: string;
  locale?: string;
  month_start_day?: number;
}

export interface Account {
  id: string;
  name: string;
  type: AccountType;
  currency: string;
  balance_minor: number;
  description?: string;
  display_group?: string;
  active?: boolean;
  updated_at?: string;
}

export interface Category {
  id?: string;
  name?: string;
  type?: string;
  [key: string]: unknown;
}

export interface TransactionSource {
  type?: string;
  expected_billing_date?: string | null;
  actual_billing_date?: string | null;
  expected_amount_minor?: number | null;
  expected_currency?: string | null;
  [key: string]: unknown;
}

export interface Transaction {
  id: string;
  date: string;
  kind: TransactionKind;
  amount_minor: number;
  currency: string;
  title: string;
  category: string;
  account_id?: string | null;
  to_account_id?: string | null;
  base_amount_minor?: number | null;
  base_currency?: string | null;
  exchange_rate_id?: string | null;
  subscription_id?: string | null;
  merchant?: string;
  notes?: string;
  tags?: string[];
  needs_review?: boolean;
  review_reason?: string;
  created_at?: string;
  updated_at?: string;
  source?: TransactionSource;
  [key: string]: unknown;
}

export interface Budget {
  id?: string;
  name: string;
  group?: string;
  category: string;
  period?: string;
  limit_minor: number;
  currency?: string;
  active?: boolean;
  [key: string]: unknown;
}

export interface Subscription {
  id: string;
  name: string;
  description?: string;
  amount_minor: number;
  currency: string;
  cadence: string;
  next_billing_date: string;
  payment_account_id?: string;
  category?: string;
  active?: boolean;
  [key: string]: unknown;
}

export interface ExchangeRate {
  id: string;
  date: string;
  from: string;
  to: string;
  rate: number;
  estimate?: boolean;
  [key: string]: unknown;
}

export interface AccountSnapshot {
  status: SnapshotStatus;
  selected_month: string;
  source_month: string | null;
  revision: number | null;
  created_at: string | null;
  updated_at: string | null;
  capture_type: string | null;
  reason: string;
  carried_forward: boolean;
  restated: boolean;
  history_enabled: boolean;
  tracking_started_month: string | null;
  base_currency: string;
  timezone: string;
  accounts: Account[];
}

export interface BookResponse {
  schema_version: number;
  profile: LedgerProfile;
  dashboard_month: string;
  current_month: string;
  account_snapshot: AccountSnapshot;
  accounts: Account[];
  categories: Category[];
  budgets: Budget[];
  transactions: Transaction[];
  subscriptions: Subscription[];
  exchange_rates: ExchangeRate[];
  metadata: Record<string, unknown>;
}

export interface MonthIndex {
  months: string[];
  current_month: string;
}

export interface AnalysisError {
  code: string;
  message: string;
}

export interface AnalysisStatus {
  state: AnalysisState;
  run_id: string;
  busy: boolean;
  started_at: number;
  finished_at: number;
  elapsed_s: number;
  window: string;
  report_url: string | null;
  error: AnalysisError | null;
  upstream_status: number | null;
}

export interface AnalysisStartResponse {
  upstream_status: number;
  report_url: string;
  agent_message: string;
  analysis: AnalysisStatus;
}

export interface ControllerFilters {
  search: string;
  kind: KindFilter;
  accountId: string;
  page: number;
  pageSize: number;
}

export interface AccountDisplayRow extends Account {
  signed_balance_minor: number;
}

export interface AccountDisplayGroup {
  name: string;
  accounts: AccountDisplayRow[];
}

export interface NativeBalanceGroup {
  currency: string;
  balance_minor: number;
  account_count: number;
}

export interface AccountSummary {
  available: boolean;
  base_currency: string;
  base_net_worth_minor: number | null;
  base_assets_minor: number;
  base_liabilities_minor: number;
  base_receivables_minor: number;
  groups: AccountDisplayGroup[];
  foreign_balances: NativeBalanceGroup[];
}

export interface NativeCashFlowGroup {
  currency: string;
  income_minor: number;
  expense_minor: number;
  transaction_count: number;
}

export interface CashFlowSummary {
  base_currency: string;
  income_minor: number;
  expense_minor: number;
  net_minor: number;
  conversion_complete: boolean;
  unconverted: NativeCashFlowGroup[];
}

export interface NaturalWeekBucket {
  start_date: string;
  end_date: string;
  income_minor: number;
  expense_minor: number;
  net_minor: number;
  has_activity: boolean;
  conversion_complete: boolean;
}

export interface NativeSpendingGroup {
  currency: string;
  expense_minor: number;
  transaction_count: number;
}

export interface TransactionPage {
  items: Transaction[];
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  source_items: number;
}

export interface SubscriptionView {
  id: string;
  name: string;
  description: string;
  amount_minor: number;
  currency: string;
  cadence: string;
  next_billing_date: string;
  payment_account_id: string;
  expected_dates: string[];
  observed_count: number;
  observed_charges: Array<{
    id: string;
    date: string;
    amount_minor: number;
    currency: string;
  }>;
  status: "observed" | "expected" | "not_due" | "unexpected" | "mismatch";
}

export interface SubscriptionCurrencyTotal {
  currency: string;
  expected_minor: number;
  observed_minor: number;
  subscription_count: number;
}

export interface SubscriptionSummary {
  rows: SubscriptionView[];
  totals: SubscriptionCurrencyTotal[];
}

export interface BudgetProgress {
  id: string;
  name: string;
  group: string;
  category: string;
  currency: string;
  limit_minor: number;
  spent_minor: number;
  ratio: number;
  status: "ok" | "watch" | "over" | "partial";
  conversion_complete: boolean;
  native_spending: NativeSpendingGroup[];
}
