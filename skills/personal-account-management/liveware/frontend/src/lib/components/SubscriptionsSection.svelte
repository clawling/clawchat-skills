<script lang="ts">
  import CalendarClockIcon from "@lucide/svelte/icons/calendar-clock";
  import { Badge } from "$lib/components/ui/badge";
  import * as Card from "$lib/components/ui/card";
  import { formatDate, formatInteger, formatMoneyWithCode } from "$lib/format";
  import type { TranslationKey } from "$lib/i18n";
  import { summarizeSubscriptions } from "$lib/selectors";
  import type { BookResponse, Language, SubscriptionView } from "$lib/types";

  type Props = {
    book: BookResponse;
    language: Language;
    t: (key: TranslationKey) => string;
  };

  let { book, language, t }: Props = $props();

  const summary = $derived(summarizeSubscriptions(book));
  const accountNames = $derived(new Map(
    book.account_snapshot.accounts.map((account) => [account.id, account.name]),
  ));

  function statusKey(status: SubscriptionView["status"]): TranslationKey {
    if (status === "observed") return "subscriptionObserved";
    if (status === "expected") return "subscriptionExpected";
    if (status === "unexpected") return "subscriptionUnexpected";
    if (status === "mismatch") return "subscriptionMismatch";
    return "subscriptionNotDue";
  }

  function cadenceKey(cadence: string): TranslationKey {
    if (cadence === "custom") return "cadenceCustom";
    if (cadence === "weekly") return "cadenceWeekly";
    if (cadence === "quarterly") return "cadenceQuarterly";
    if (cadence === "yearly") return "cadenceYearly";
    return "cadenceMonthly";
  }
</script>

<section class="activity-section" aria-labelledby="subscriptions-title">
  <div class="activity-heading">
    <div>
      <p class="module-eyebrow">{formatInteger(summary.rows.length, language)} {t("subscriptionsLower")}</p>
      <h2 id="subscriptions-title">{t("subscriptionsTitle")}</h2>
      <p>{t("subscriptionsDescription")}</p>
    </div>
  </div>

  {#if summary.totals.length > 0}
    <div class="subscription-totals" aria-label={t("selectedMonthTotals")}>
      {#each summary.totals as total (total.currency)}
        <Card.Root size="sm">
          <Card.Content>
            <span>{t("selectedMonthTotals")}</span>
            <div class="subscription-total-pair">
              <span>{t("subscriptionExpected")}</span>
              <strong>{formatMoneyWithCode(total.expected_minor, total.currency, language)}</strong>
            </div>
            <div class="subscription-total-pair">
              <span>{t("subscriptionObserved")}</span>
              <strong>{formatMoneyWithCode(total.observed_minor, total.currency, language)}</strong>
            </div>
            <small>{total.subscription_count} {t("subscriptionsLower")}</small>
          </Card.Content>
        </Card.Root>
      {/each}
    </div>
  {/if}

  {#if summary.rows.length === 0}
    <Card.Root>
      <Card.Content class="activity-empty">
        <h3>{t("noSubscriptions")}</h3>
        <p>{t("noSubscriptionsDescription")}</p>
      </Card.Content>
    </Card.Root>
  {:else}
    <div class="subscription-grid">
      {#each summary.rows as subscription (subscription.id)}
        <Card.Root class="subscription-card" data-status={subscription.status}>
          <Card.Header>
            <div class="subscription-title-row">
              <div>
                <Card.Title>{subscription.name}</Card.Title>
                <Card.Description>
                  {subscription.description || t(cadenceKey(subscription.cadence))}
                </Card.Description>
              </div>
              <Badge variant={subscription.status === "mismatch" ? "destructive" : "outline"}>
                {t(statusKey(subscription.status))}
              </Badge>
            </div>
          </Card.Header>
          <Card.Content class="subscription-content">
            <strong class="subscription-amount">
              {formatMoneyWithCode(subscription.amount_minor, subscription.currency, language)}
            </strong>
            <dl>
              <div>
                <dt>{t("cadence")}</dt>
                <dd>{t(cadenceKey(subscription.cadence))}</dd>
              </div>
              <div>
                <dt>{t("nextBilling")}</dt>
                <dd>{formatDate(subscription.next_billing_date, language)}</dd>
              </div>
              <div>
                <dt>{t("paymentAccount")}</dt>
                <dd>{accountNames.get(subscription.payment_account_id) ?? t("unknownAccount")}</dd>
              </div>
            </dl>
            <div class="subscription-observation">
              <CalendarClockIcon aria-hidden="true" />
              <div>
                {#if subscription.expected_dates.length > 0}
                  <p>{t("expectedThisMonth")}</p>
                  <span>{subscription.expected_dates.map((date) => formatDate(date, language)).join(" · ")}</span>
                {:else}
                  <p>{t("notExpectedThisMonth")}</p>
                {/if}
                {#if subscription.observed_count > 0}
                  <small>{subscription.observed_count} {t("observedCharges")}</small>
                  <ul class="subscription-observed-list">
                    {#each subscription.observed_charges as charge (charge.id)}
                      <li>
                        <span>{formatDate(charge.date, language)}</span>
                        <strong>{formatMoneyWithCode(charge.amount_minor, charge.currency, language)}</strong>
                      </li>
                    {/each}
                  </ul>
                {/if}
              </div>
            </div>
          </Card.Content>
        </Card.Root>
      {/each}
    </div>
  {/if}
</section>
