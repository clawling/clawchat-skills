<script lang="ts">
  import ArrowLeftIcon from "@lucide/svelte/icons/arrow-left";
  import ArrowRightIcon from "@lucide/svelte/icons/arrow-right";
  import SearchIcon from "@lucide/svelte/icons/search";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card";
  import { Input } from "$lib/components/ui/input";
  import { formatDate, formatInteger, formatMoneyWithCode } from "$lib/format";
  import type { TranslationKey } from "$lib/i18n";
  import { selectTransactions } from "$lib/selectors";
  import type { BookResponse, KindFilter, Language, Transaction } from "$lib/types";

  type Props = {
    book: BookResponse;
    language: Language;
    t: (key: TranslationKey) => string;
    search: string;
    kindFilter: KindFilter;
    accountFilter: string;
    page: number;
    pageSize: number;
    onSearch: (value: string) => void;
    onKindFilter: (value: KindFilter) => void;
    onAccountFilter: (value: string) => void;
    onPage: (value: number) => void;
  };

  let {
    book,
    language,
    t,
    search,
    kindFilter,
    accountFilter,
    page,
    pageSize,
    onSearch,
    onKindFilter,
    onAccountFilter,
    onPage,
  }: Props = $props();

  const accounts = $derived(book.account_snapshot.accounts);
  const accountNames = $derived(new Map(accounts.map((account) => [account.id, account.name])));
  const transactionPage = $derived(selectTransactions(book, {
    search,
    kind: kindFilter,
    accountId: accountFilter,
    page,
    pageSize,
  }));

  $effect(() => {
    if (transactionPage.page !== page) onPage(transactionPage.page);
  });

  const kinds: { value: KindFilter; label: TranslationKey }[] = [
    { value: "all", label: "filterAll" },
    { value: "income", label: "income" },
    { value: "expense", label: "expense" },
    { value: "transfer", label: "transfer" },
    { value: "review", label: "needsReview" },
  ];

  function accountLabel(id: string | null | undefined): string {
    return id ? (accountNames.get(id) ?? t("unknownAccount")) : t("unknownAccount");
  }

  function kindLabel(transaction: Transaction): string {
    if (transaction.kind === "income") return t("income");
    if (transaction.kind === "transfer") return t("transfer");
    return t("expense");
  }

  function signedAmount(transaction: Transaction): string {
    const amount = formatMoneyWithCode(transaction.amount_minor, transaction.currency, language);
    if (transaction.kind === "income") return `+${amount}`;
    if (transaction.kind === "expense") return `−${amount}`;
    return amount;
  }
</script>

<section class="activity-section" aria-labelledby="transactions-title">
  <div class="activity-heading">
    <div>
      <p class="module-eyebrow">{formatInteger(transactionPage.total_items, language)} {t("records")}</p>
      <h2 id="transactions-title">{t("transactionsTitle")}</h2>
      <p>{t("transactionsDescription")}</p>
    </div>
  </div>

  <Card.Root>
    <Card.Content class="activity-controls">
      <label class="search-control">
        <span class="sr-only">{t("searchTransactions")}</span>
        <SearchIcon aria-hidden="true" />
        <Input
          type="search"
          value={search}
          placeholder={t("searchPlaceholder")}
          oninput={(event) => onSearch(event.currentTarget.value)}
        />
      </label>
      <label class="account-filter-control">
        <span>{t("account")}</span>
        <select value={accountFilter} onchange={(event) => onAccountFilter(event.currentTarget.value)}>
          <option value="">{t("allAccounts")}</option>
          {#if accountFilter && !accountNames.has(accountFilter)}
            <option value={accountFilter}>{t("unavailableAccount")}</option>
          {/if}
          {#each accounts as account (account.id)}
            <option value={account.id}>{account.name}</option>
          {/each}
        </select>
      </label>
      <fieldset class="kind-filters">
        <legend class="sr-only">{t("transactionTypeFilter")}</legend>
        {#each kinds as kind (kind.value)}
          <Button
            size="sm"
            variant={kindFilter === kind.value ? "default" : "ghost"}
            aria-pressed={kindFilter === kind.value}
            onclick={() => onKindFilter(kind.value)}
          >
            {t(kind.label)}
          </Button>
        {/each}
      </fieldset>
    </Card.Content>
  </Card.Root>

  {#if transactionPage.total_items === 0}
    <Card.Root>
      <Card.Content class="activity-empty">
        <h3>{transactionPage.source_items === 0 ? t("noTransactions") : t("noMatchingTransactions")}</h3>
        <p>{transactionPage.source_items === 0 ? t("noTransactionsDescription") : t("noMatchingDescription")}</p>
      </Card.Content>
    </Card.Root>
  {:else}
    <div class="transaction-list">
      {#each transactionPage.items as transaction (transaction.id)}
        <article class="transaction-row" data-kind={transaction.kind}>
          <div class="transaction-date">
            <span>{formatDate(transaction.date, language)}</span>
            <small>{kindLabel(transaction)}</small>
          </div>
          <div class="transaction-copy">
            <div class="transaction-title-line">
              <strong>{transaction.title}</strong>
              {#if transaction.needs_review}
                <Badge variant="outline">{t("needsReview")}</Badge>
              {/if}
            </div>
            <p>
              {#if transaction.merchant}<span>{transaction.merchant}</span>{/if}
              <span>{transaction.category}</span>
              {#if transaction.kind === "transfer"}
                <span>{accountLabel(transaction.account_id)} → {accountLabel(transaction.to_account_id)}</span>
              {:else}
                <span>{accountLabel(transaction.account_id)}</span>
              {/if}
            </p>
          </div>
          <div class="transaction-amount">
            <strong>{signedAmount(transaction)}</strong>
            {#if typeof transaction.base_amount_minor === "number"
              && transaction.base_currency
              && transaction.base_currency !== transaction.currency}
              <span>{t("recordedBase")}: {formatMoneyWithCode(transaction.base_amount_minor, transaction.base_currency, language)}</span>
            {/if}
          </div>
        </article>
      {/each}
    </div>

    <nav class="pagination" aria-label={t("transactionPages")}>
      <Button
        variant="outline"
        size="icon"
        aria-label={t("previousPage")}
        disabled={transactionPage.page <= 1}
        onclick={() => onPage(transactionPage.page - 1)}
      >
        <ArrowLeftIcon aria-hidden="true" />
      </Button>
      <span>
        {t("page")} {transactionPage.page} / {transactionPage.total_pages}
      </span>
      <Button
        variant="outline"
        size="icon"
        aria-label={t("nextPage")}
        disabled={transactionPage.page >= transactionPage.total_pages}
        onclick={() => onPage(transactionPage.page + 1)}
      >
        <ArrowRightIcon aria-hidden="true" />
      </Button>
    </nav>
  {/if}
</section>
