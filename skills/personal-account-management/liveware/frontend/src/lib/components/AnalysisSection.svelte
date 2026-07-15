<script lang="ts">
  import BrainCircuitIcon from "@lucide/svelte/icons/brain-circuit";
  import CircleCheckIcon from "@lucide/svelte/icons/circle-check";
  import ExternalLinkIcon from "@lucide/svelte/icons/external-link";
  import LoaderCircleIcon from "@lucide/svelte/icons/loader-circle";
  import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card";
  import { formatMonth } from "$lib/format";
  import type { TranslationKey } from "$lib/i18n";
  import type { AnalysisStatus, Language } from "$lib/types";

  type Props = {
    analysis: AnalysisStatus;
    analysisLaunching: boolean;
    selectedMonth: string;
    language: Language;
    t: (key: TranslationKey) => string;
    onRun: () => void | Promise<void>;
  };

  let {
    analysis,
    analysisLaunching,
    selectedMonth,
    language,
    t,
    onRun,
  }: Props = $props();

  const displayedMonth = $derived(
    /\b\d{4}-(0[1-9]|1[0-2])\b/.exec(analysis.window)?.[0] ?? selectedMonth,
  );
  const isRunning = $derived(analysis.state === "running" || analysis.busy);
  const actionDisabled = $derived(isRunning || analysisLaunching || !selectedMonth);

  function elapsedLabel(seconds: number): string {
    const safe = Math.max(0, Math.round(seconds || 0));
    const minutes = Math.floor(safe / 60);
    const remaining = safe % 60;
    return minutes > 0
      ? `${minutes}${t("minutesShort")} ${remaining}${t("secondsShort")}`
      : `${remaining}${t("secondsShort")}`;
  }

  function failureMessage(): string {
    const code = analysis.error?.code;
    if (code === "analysis_client_timeout") return t("analysisClientTimeoutDetail");
    if (code === "analysis_timeout") return t("analysisTimeoutDetail");
    if (code === "upstream_failed") return t("analysisServiceFailedDetail");
    if (["report_failed", "report_missing", "report_publish_failed"].includes(code ?? "")) {
      return t("analysisReportFailedDetail");
    }
    if (["template_missing", "prompt_render_failed"].includes(code ?? "")) {
      return t("analysisSetupFailedDetail");
    }
    return t("analysisFailedDetail");
  }

  function stateLabel(): string {
    if (isRunning) return t("analysisRunning");
    if (analysisLaunching) return t("analysisStarting");
    if (analysis.state === "succeeded") return t("analysisSucceeded");
    if (analysis.state === "failed") return t("analysisFailed");
    return t("analysisReady");
  }
</script>

<section class="analysis-section" aria-labelledby="analysis-title">
  <div class="activity-heading">
    <div>
      <p class="module-eyebrow">{t("navAnalysis")}</p>
      <h2 id="analysis-title">{t("analysisTitle")}</h2>
      <p>{t("analysisDescription")}</p>
    </div>
  </div>

  <Card.Root class="analysis-card" data-state={analysis.state} aria-live="polite" aria-busy={isRunning || analysisLaunching}>
    <Card.Header>
      <div class="analysis-status-heading">
        <div class="analysis-icon" aria-hidden="true">
          {#if isRunning || analysisLaunching}
            <LoaderCircleIcon class="analysis-spinner" />
          {:else if analysis.state === "succeeded"}
            <CircleCheckIcon />
          {:else if analysis.state === "failed"}
            <TriangleAlertIcon />
          {:else}
            <BrainCircuitIcon />
          {/if}
        </div>
        <div>
          <Card.Title>{stateLabel()}</Card.Title>
          <Card.Description>
            {t("analysisForMonth")} {formatMonth(displayedMonth, language)}
          </Card.Description>
        </div>
        <Badge variant={analysis.state === "failed" ? "destructive" : "outline"}>
          {stateLabel()}
        </Badge>
      </div>
    </Card.Header>

    <Card.Content class="analysis-content">
      {#if isRunning}
        <p>{t("analysisRunningDetail")}</p>
        <small>{t("analysisElapsed")} {elapsedLabel(analysis.elapsed_s)}</small>
      {:else if analysisLaunching}
        <p>{t("analysisStarting")}</p>
      {:else if analysis.state === "succeeded"}
        <p>{t("analysisSucceededDetail")}</p>
      {:else if analysis.state === "failed"}
        <p>{failureMessage()}</p>
      {:else}
        <p>{t("analysisReadyDetail")}</p>
      {/if}

      <div class="analysis-actions">
        {#if analysis.state === "succeeded" && analysis.report_url}
          <Button href={analysis.report_url} target="_blank" rel="noopener noreferrer">
            {t("analysisOpenReport")}
            <ExternalLinkIcon aria-hidden="true" data-icon="inline-end" />
          </Button>
        {/if}
        <Button
          variant={analysis.state === "succeeded" ? "outline" : "default"}
          disabled={actionDisabled}
          onclick={() => void onRun()}
        >
          {analysis.state === "failed" ? t("analysisRetry") : t("analysisRun")}
        </Button>
      </div>
    </Card.Content>
  </Card.Root>
</section>
