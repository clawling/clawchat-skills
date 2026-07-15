<script lang="ts">
  import { formatMoney, formatWeekRange } from "$lib/format";
  import type { TranslationKey } from "$lib/i18n";
  import type { Language, NaturalWeekBucket } from "$lib/types";

  type Props = {
    buckets: NaturalWeekBucket[];
    currency: string;
    language: Language;
    t: (key: TranslationKey) => string;
  };

  let { buckets, currency, language, t }: Props = $props();

  const chartWidth = 720;
  const baseline = 178;
  const plotHeight = 132;
  const groupWidth = $derived(620 / Math.max(1, buckets.length));
  const barWidth = $derived(Math.min(26, groupWidth * 0.26));
  const maximum = $derived(
    Math.max(1, ...buckets.flatMap((bucket) => [bucket.income_minor, bucket.expense_minor])),
  );
  const hasActivity = $derived(buckets.some((bucket) => bucket.has_activity));
  const conversionComplete = $derived(buckets.every((bucket) => bucket.conversion_complete));

  function height(value: number): number {
    return Math.max(value === 0 ? 0 : 2, (value / maximum) * plotHeight);
  }

  function center(index: number): number {
    return 50 + groupWidth * index + groupWidth / 2;
  }
</script>

<div class="cashflow-chart">
  <div class="chart-heading">
    <div>
      <p class="module-eyebrow">{t("naturalWeeks")}</p>
      <h3>{t("cashFlowChart")}</h3>
    </div>
    <div class="chart-legend" aria-label={t("chartLegend")}>
      <span><i class="legend-income"></i>{t("income")}</span>
      <span><i class="legend-expense"></i>{t("expense")}</span>
    </div>
  </div>

  {#if hasActivity}
    <div class="chart-scroll">
      <svg
        viewBox={`0 0 ${chartWidth} 222`}
        role="img"
        aria-labelledby="cashflow-chart-title cashflow-chart-description"
      >
        <title id="cashflow-chart-title">{t("cashFlowChart")}</title>
        <desc id="cashflow-chart-description">{t("cashFlowChartDescription")}</desc>
        <line class="chart-baseline" x1="38" x2="700" y1={baseline} y2={baseline} />
        {#each buckets as bucket, index (`${bucket.start_date}:${bucket.end_date}`)}
          {@const incomeHeight = height(bucket.income_minor)}
          {@const expenseHeight = height(bucket.expense_minor)}
          <g>
            <rect
              class="chart-bar chart-bar--income"
              x={center(index) - barWidth - 2}
              y={baseline - incomeHeight}
              width={barWidth}
              height={incomeHeight}
              rx="4"
            >
              <title>{t("income")}: {formatMoney(bucket.income_minor, currency, language)}</title>
            </rect>
            <rect
              class="chart-bar chart-bar--expense"
              x={center(index) + 2}
              y={baseline - expenseHeight}
              width={barWidth}
              height={expenseHeight}
              rx="4"
            >
              <title>{t("expense")}: {formatMoney(bucket.expense_minor, currency, language)}</title>
            </rect>
            <text class="chart-axis-label" x={center(index)} y="204" text-anchor="middle">
              {formatWeekRange(bucket.start_date, bucket.end_date, language)}
            </text>
            {#if !bucket.conversion_complete}
              <text class="chart-gap-marker" x={center(index)} y="218" text-anchor="middle">*</text>
            {/if}
          </g>
        {/each}
      </svg>
    </div>
    {#if !conversionComplete}
      <p class="chart-note">* {t("partialConversionNote")}</p>
    {/if}
    <table class="sr-only">
      <caption>{t("cashFlowChartDescription")}</caption>
      <thead>
        <tr>
          <th scope="col">{t("week")}</th>
          <th scope="col">{t("income")}</th>
          <th scope="col">{t("expense")}</th>
          <th scope="col">{t("conversionStatus")}</th>
        </tr>
      </thead>
      <tbody>
        {#each buckets as bucket (`table:${bucket.start_date}:${bucket.end_date}`)}
          <tr>
            <th scope="row">{formatWeekRange(bucket.start_date, bucket.end_date, language)}</th>
            <td>{formatMoney(bucket.income_minor, currency, language)}</td>
            <td>{formatMoney(bucket.expense_minor, currency, language)}</td>
            <td>{bucket.conversion_complete ? t("complete") : t("partial")}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <div class="chart-empty">
      <p>{t("noCashFlow")}</p>
    </div>
  {/if}
</div>
