<script lang="ts">
  import CashFlowChart from "$lib/components/CashFlowChart.svelte";
  import { Badge } from "$lib/components/ui/badge";
  import * as Card from "$lib/components/ui/card";
  import { formatMoney, formatMoneyWithCode, formatMonth, formatPercent } from "$lib/format";
  import type { TranslationKey } from "$lib/i18n";
  import {
    buildBudgetProgress,
    buildNaturalWeekBuckets,
    summarizeAccounts,
    summarizeCashFlow,
  } from "$lib/selectors";
  import type { BookResponse, Language } from "$lib/types";

  type Props = {
    book: BookResponse;
    language: Language;
    t: (key: TranslationKey) => string;
  };

  let { book, language, t }: Props = $props();

  const accounts = $derived(summarizeAccounts(book));
  const cashFlow = $derived(summarizeCashFlow(book));
  const budgets = $derived(buildBudgetProgress(book));
  const weeks = $derived(buildNaturalWeekBuckets(book));
  const snapshot = $derived(book.account_snapshot);

  function accountTypeLabel(type: string): string {
    if (type === "liability") return t("liability");
    if (type === "receivable") return t("receivable");
    return t("asset");
  }
</script>

<section class="overview-section" aria-label={t("navOverview")}>
  <div class="snapshot-banner" data-status={snapshot.status}>
    <div>
      <strong>
        {#if snapshot.status === "unavailable"}
          {t("historyUnavailable")}
        {:else if snapshot.restated}
          {t("restatedSnapshot")}
        {:else if snapshot.carried_forward}
          {t("carriedSnapshot")}
        {:else}
          {t("recordedSnapshot")}
        {/if}
      </strong>
      <span>
        {#if snapshot.source_month}
          {t("snapshotSource")} {formatMonth(snapshot.source_month, language)}
        {:else}
          {t("historyUnavailableDetail")}
        {/if}
      </span>
    </div>
    {#if snapshot.revision !== null}
      <Badge variant={snapshot.restated ? "secondary" : "outline"}>
        {t("revision")} {snapshot.revision}
      </Badge>
    {/if}
  </div>

  <div class="overview-metrics-grid">
    <Card.Root class="net-worth-card">
      <Card.Header>
        <Card.Title>{t("baseNetWorth")}</Card.Title>
        <Card.Description>{t("baseNetWorthDescription")}</Card.Description>
      </Card.Header>
      <Card.Content class="flex flex-1 flex-col">
        <p class="net-worth-value">
          {accounts.base_net_worth_minor === null
            ? "—"
            : formatMoney(accounts.base_net_worth_minor, accounts.base_currency, language)}
        </p>
        {#if accounts.available}
          <div class="net-worth-breakdown">
            <span>{t("assets")} <strong>{formatMoney(accounts.base_assets_minor, accounts.base_currency, language)}</strong></span>
            <span>{t("receivables")} <strong>{formatMoney(accounts.base_receivables_minor, accounts.base_currency, language)}</strong></span>
            <span>{t("liabilities")} <strong>−{formatMoney(accounts.base_liabilities_minor, accounts.base_currency, language)}</strong></span>
          </div>
          {#if accounts.foreign_balances.length > 0}
            <div class="native-balance-list">
              <p>{t("unconvertedBalances")}</p>
              {#each accounts.foreign_balances as row (row.currency)}
                <span>
                  {formatMoneyWithCode(row.balance_minor, row.currency, language)}
                  <small>{row.account_count} {t("accountsLower")}</small>
                </span>
              {/each}
            </div>
          {/if}
        {:else}
          <p class="net-worth-unavailable">{t("historyUnavailableDetail")}</p>
        {/if}
      </Card.Content>
    </Card.Root>

    <Card.Root class="cashflow-card">
      <Card.Header>
        <Card.Title>{t("cashFlow")}</Card.Title>
        <Card.Description>{t("cashFlowDescription")}</Card.Description>
      </Card.Header>
      <Card.Content>
        <dl class="cashflow-metrics">
          <div><dt>{t("income")}</dt><dd>{formatMoney(cashFlow.income_minor, cashFlow.base_currency, language)}</dd></div>
          <div><dt>{t("expense")}</dt><dd>{formatMoney(cashFlow.expense_minor, cashFlow.base_currency, language)}</dd></div>
          <div class="cashflow-net"><dt>{t("net")}</dt><dd>{formatMoney(cashFlow.net_minor, cashFlow.base_currency, language)}</dd></div>
        </dl>
        {#if !cashFlow.conversion_complete}
          <div class="partial-cashflow">
            <Badge variant="outline">{t("partial")}</Badge>
            <p>{t("partialConversionNote")}</p>
            {#each cashFlow.unconverted as row (row.currency)}
              <span>
                +{formatMoneyWithCode(row.income_minor, row.currency, language)} / −{formatMoneyWithCode(row.expense_minor, row.currency, language)}
              </span>
            {/each}
          </div>
        {/if}
      </Card.Content>
    </Card.Root>
  </div>

  <Card.Root class="chart-card">
    <Card.Content>
      <CashFlowChart
        buckets={weeks}
        currency={cashFlow.base_currency}
        {language}
        {t}
      />
    </Card.Content>
  </Card.Root>

  <div class="overview-detail-grid">
    <Card.Root>
      <Card.Header>
        <Card.Title>{t("accountsTitle")}</Card.Title>
        <Card.Description>{t("accountsDescription")}</Card.Description>
      </Card.Header>
      <Card.Content>
        {#if !accounts.available}
          <p class="muted-copy">{t("historyUnavailableDetail")}</p>
        {:else if accounts.groups.length === 0}
          <p class="muted-copy">{t("noAccounts")}</p>
        {:else}
          <div class="account-groups">
            {#each accounts.groups as group (group.name)}
              <section class="account-group">
                <h3>{group.name}</h3>
                {#each group.accounts as account (account.id)}
                  <div class="account-row">
                    <div>
                      <strong>{account.name}</strong>
                      <span>{accountTypeLabel(account.type)} · {account.currency}</span>
                    </div>
                    <b>{formatMoney(account.signed_balance_minor, account.currency, language)}</b>
                  </div>
                {/each}
              </section>
            {/each}
          </div>
        {/if}
      </Card.Content>
    </Card.Root>

    <Card.Root>
      <Card.Header>
        <Card.Title>{t("budgetProgress")}</Card.Title>
        <Card.Description>{t("budgetDescription")}</Card.Description>
      </Card.Header>
      <Card.Content>
        {#if budgets.length === 0}
          <p class="muted-copy">{t("noBudgets")}</p>
        {:else}
          <div class="budget-list">
            {#each budgets as budget (budget.id)}
              <div class="budget-row" data-status={budget.status}>
                <div class="budget-row__heading">
                  <div><strong>{budget.name}</strong><span>{budget.group || budget.category}</span></div>
                  <b>{formatPercent(budget.ratio * 100, language)}</b>
                </div>
                <progress
                  aria-label={`${budget.name} · ${t("budgetProgress")}`}
                  max="100"
                  value={Math.min(100, budget.ratio * 100)}
                >
                  {formatPercent(budget.ratio * 100, language)}
                </progress>
                <p>
                  {formatMoney(budget.spent_minor, budget.currency, language)} / {formatMoney(budget.limit_minor, budget.currency, language)}
                  {#if !budget.conversion_complete} · {t("partial")}{/if}
                </p>
                {#if budget.native_spending.length > 0}
                  <div class="budget-native-spending">
                    {#each budget.native_spending as native (native.currency)}
                      <span>
                        {formatMoneyWithCode(native.expense_minor, native.currency, language)} · {t("excludedFromProgress")}
                      </span>
                    {/each}
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      </Card.Content>
    </Card.Root>
  </div>
</section>
