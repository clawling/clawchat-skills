<script lang="ts">
  import { onMount } from "svelte";
  import { toast } from "svelte-sonner";
  import AnalysisSection from "$lib/components/AnalysisSection.svelte";
  import BottomNav from "$lib/components/BottomNav.svelte";
  import DashboardHeader from "$lib/components/DashboardHeader.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import OverviewSection from "$lib/components/OverviewSection.svelte";
  import SubscriptionsSection from "$lib/components/SubscriptionsSection.svelte";
  import TransactionsSection from "$lib/components/TransactionsSection.svelte";
  import { Toaster } from "$lib/components/ui/sonner";
  import { dashboardController as controller } from "$lib/dashboard-controller.svelte";
  import { formatMonth } from "$lib/format";
  import { languageFromSearch, loadErrorDescriptionKey, translator } from "$lib/i18n";

  const language = languageFromSearch();
  const t = translator(language);
  const displayedMonth = $derived(
    controller.book?.dashboard_month ?? controller.selectedMonth,
  );
  const displayedPeriod = $derived(
    displayedMonth ? formatMonth(displayedMonth, language) : "",
  );
  const loadErrorDescription = $derived(t(loadErrorDescriptionKey(controller.error)));
  let outageToastShown = false;

  $effect(() => {
    if (!controller.error) {
      outageToastShown = false;
    } else if (controller.book && !outageToastShown) {
      outageToastShown = true;
      toast.error(t("loadError"), { description: loadErrorDescription });
    }
  });

  onMount(() => {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
    controller.start();
    return () => controller.stop();
  });
</script>

<svelte:head>
  <title>{t("appTitle")}</title>
  <meta name="description" content={t("appDescription")} />
</svelte:head>

<div class="dashboard-shell">
  <DashboardHeader
    {language}
    months={controller.months}
    selectedMonth={controller.selectedMonth}
    currentMonth={controller.currentMonth}
    {t}
    onMonthChange={(month) => controller.selectMonth(month)}
  />

  {#if controller.initialLoading}
    <main class="dashboard-container loading-shell" aria-live="polite">
      <div>
        <div class="loading-shell__mark" aria-hidden="true"></div>
        <p>{t("loading")}</p>
      </div>
    </main>
  {:else if controller.error && !controller.book}
    <main class="dashboard-container dashboard-main">
      <EmptyState
        role="alert"
        title={t("loadError")}
        description={loadErrorDescription}
        actionLabel={t("retry")}
        onAction={() => void controller.refresh({ refreshMonths: true })}
      />
    </main>
  {:else if !controller.book}
    <main class="dashboard-container loading-shell" aria-live="polite">
      <div>
        <div class="loading-shell__mark" aria-hidden="true"></div>
        <p>{t("loading")}</p>
      </div>
    </main>
  {:else}
    <main class="dashboard-container dashboard-main">
      <section class="dashboard-intro" aria-labelledby="dashboard-title">
        <div>
          <p class="module-eyebrow">{displayedPeriod || t("currentMonth")}</p>
          <h1 id="dashboard-title">{t("overviewTitle")}</h1>
        </div>
        <p>{t("overviewLead")}</p>
      </section>

      <BottomNav
        active={controller.activeSection}
        {t}
        onChange={(section) => controller.setActiveSection(section)}
      />

      {#if controller.activeSection === "overview"}
        <OverviewSection book={controller.book} {language} {t} />
      {:else if controller.activeSection === "transactions"}
        <TransactionsSection
          book={controller.book}
          {language}
          {t}
          search={controller.search}
          kindFilter={controller.kindFilter}
          accountFilter={controller.accountFilter}
          page={controller.page}
          pageSize={controller.pageSize}
          onSearch={(value) => controller.setSearch(value)}
          onKindFilter={(value) => controller.setKindFilter(value)}
          onAccountFilter={(value) => controller.setAccountFilter(value)}
          onPage={(value) => controller.setPage(value)}
        />
      {:else if controller.activeSection === "subscriptions"}
        <SubscriptionsSection book={controller.book} {language} {t} />
      {:else}
        <AnalysisSection
          analysis={controller.analysis}
          analysisLaunching={controller.analysisLaunching}
          selectedMonth={controller.selectedMonth}
          {language}
          {t}
          onRun={() => controller.runAnalysis()}
        />
      {/if}
    </main>
  {/if}

  <Toaster position="top-right" richColors closeButton />
</div>
