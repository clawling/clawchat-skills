<script lang="ts">
  import { Badge } from "$lib/components/ui/badge";
  import { formatMonth } from "$lib/format";
  import type { TranslationKey } from "$lib/i18n";
  import type { Language } from "$lib/types";

  type Props = {
    language: Language;
    months: string[];
    selectedMonth: string;
    currentMonth: string;
    t: (key: TranslationKey) => string;
    onMonthChange: (month: string) => void;
  };

  let {
    language,
    months,
    selectedMonth,
    currentMonth,
    t,
    onMonthChange,
  }: Props = $props();
</script>

<header class="dashboard-header">
  <div class="dashboard-container dashboard-header__inner">
    <div class="brand-lockup">
      <div class="brand-mark" aria-hidden="true">P</div>
      <div class="brand-copy">
        <p class="brand-eyebrow">{t("brandEyebrow")}</p>
        <p class="brand-title">{t("appTitle")}</p>
      </div>
    </div>

    <div class="header-actions">
      {#if selectedMonth === currentMonth && currentMonth}
        <Badge variant="secondary">{t("currentMonth")}</Badge>
      {/if}
      <div class="month-control">
        <label for="dashboard-month">{t("month")}</label>
        <select
          class="month-select"
          id="dashboard-month"
          value={selectedMonth}
          onchange={(event) => onMonthChange(event.currentTarget.value)}
        >
          {#each months as month (month)}
            <option value={month}>{formatMonth(month, language)}</option>
          {/each}
        </select>
      </div>
    </div>
  </div>
</header>
