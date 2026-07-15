<script lang="ts">
  import ChartNoAxesCombinedIcon from "@lucide/svelte/icons/chart-no-axes-combined";
  import CreditCardIcon from "@lucide/svelte/icons/credit-card";
  import ListChecksIcon from "@lucide/svelte/icons/list-checks";
  import SparklesIcon from "@lucide/svelte/icons/sparkles";
  import type { TranslationKey } from "$lib/i18n";

  type Section = "overview" | "transactions" | "subscriptions" | "analysis";
  type Item = { id: Section; label: TranslationKey; icon: typeof ChartNoAxesCombinedIcon };
  type Props = {
    active: string;
    t: (key: TranslationKey) => string;
    onChange: (section: Section) => void;
  };

  let { active, t, onChange }: Props = $props();

  const items: Item[] = [
    { id: "overview", label: "navOverview", icon: ChartNoAxesCombinedIcon },
    { id: "transactions", label: "navTransactions", icon: ListChecksIcon },
    { id: "subscriptions", label: "navSubscriptions", icon: CreditCardIcon },
    { id: "analysis", label: "navAnalysis", icon: SparklesIcon },
  ];
</script>

<nav class="dashboard-nav" aria-label={t("sectionNavigation")}>
  {#each items as item (item.id)}
    {@const Icon = item.icon}
    <button
      class="dashboard-nav__item"
      type="button"
      aria-current={active === item.id ? "page" : undefined}
      aria-label={t(item.label)}
      onclick={() => onChange(item.id)}
    >
      <Icon aria-hidden="true" />
      <span>{t(item.label)}</span>
    </button>
  {/each}
</nav>
