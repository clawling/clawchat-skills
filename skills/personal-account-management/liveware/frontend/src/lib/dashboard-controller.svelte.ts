import {
  DashboardApiError,
  fetchAnalysisStatus,
  fetchBook,
  fetchMonths,
  startAnalysis,
} from "$lib/api";
import {
  analysisRecoveryOwnsLifecycle,
  analysisStatusCanPublish,
  analysisStatusFromPayload,
  dashboardLoadErrorFrom,
  refreshFailureShouldPublish,
  requestOwnsSelection,
} from "$lib/request-ownership";
import type {
  AnalysisStatus,
  BookResponse,
  DashboardLoadError,
  DashboardSection,
  KindFilter,
} from "$lib/types";

const AUTO_REFRESH_MS = 3_000;
const REFRESH_TIMEOUT_MS = 15_000;
const ANALYSIS_CLIENT_TIMEOUT_MS = 30_000;
const ANALYSIS_STATUS_TIMEOUT_MS = 15_000;

const IDLE_ANALYSIS: AnalysisStatus = {
  state: "idle",
  run_id: "",
  busy: false,
  started_at: 0,
  finished_at: 0,
  elapsed_s: 0,
  window: "",
  report_url: null,
  error: null,
  upstream_status: null,
};

type RefreshOptions = {
  refreshMonths?: boolean;
};

export class DashboardController {
  book = $state<BookResponse | null>(null);
  months = $state<string[]>([]);
  currentMonth = $state("");
  selectedMonth = $state("");
  initialLoading = $state(true);
  refreshing = $state(false);
  error = $state<DashboardLoadError | null>(null);
  analysis = $state<AnalysisStatus>({ ...IDLE_ANALYSIS });
  analysisLaunching = $state(false);

  search = $state("");
  kindFilter = $state<KindFilter>("all");
  accountFilter = $state("");
  page = $state(1);
  pageSize = $state(20);
  activeSection = $state<DashboardSection>("overview");

  private started = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  private request: Promise<void> | null = null;
  private abortController: AbortController | null = null;
  private refreshQueued = false;
  private monthsRefreshQueued = false;
  private selectionVersion = 0;
  private analysisVersion = 0;
  private analysisRequest: Promise<void> | null = null;
  private analysisAbortController: AbortController | null = null;
  private resumeTimer: ReturnType<typeof setTimeout> | null = null;
  private lastResumeRefreshAt = 0;

  private readonly onVisibilityChange = () => {
    if (!document.hidden) this.queueResumeRefresh();
  };

  private readonly onFocus = () => {
    if (!document.hidden) this.queueResumeRefresh();
  };

  start(): void {
    if (this.started) return;
    this.started = true;
    document.addEventListener("visibilitychange", this.onVisibilityChange);
    window.addEventListener("focus", this.onFocus);
    this.timer = setInterval(() => {
      if (!document.hidden) void this.refresh({ refreshMonths: true });
    }, AUTO_REFRESH_MS);
    void this.refresh({ refreshMonths: true });
  }

  stop(): void {
    if (!this.started) return;
    this.started = false;
    document.removeEventListener("visibilitychange", this.onVisibilityChange);
    window.removeEventListener("focus", this.onFocus);
    if (this.timer !== null) clearInterval(this.timer);
    if (this.resumeTimer !== null) clearTimeout(this.resumeTimer);
    this.timer = null;
    this.resumeTimer = null;
    this.refreshQueued = false;
    this.monthsRefreshQueued = false;
    this.abortController?.abort();
    this.analysisVersion += 1;
    this.analysisLaunching = false;
    this.analysisAbortController?.abort();
  }

  private queueResumeRefresh(): void {
    const now = Date.now();
    if (this.resumeTimer !== null || now - this.lastResumeRefreshAt < 500) return;
    this.resumeTimer = setTimeout(() => {
      this.resumeTimer = null;
      if (!this.started || document.hidden) return;
      this.lastResumeRefreshAt = Date.now();
      void this.refresh({ refreshMonths: true });
    }, 0);
  }

  async refresh(options: RefreshOptions = {}): Promise<void> {
    if (this.request) {
      this.refreshQueued = true;
      this.monthsRefreshQueued ||= options.refreshMonths ?? false;
      return this.request;
    }

    const refreshMonths = options.refreshMonths ?? false;
    const task = this.performRefresh(refreshMonths);
    this.request = task;
    try {
      await task;
    } finally {
      this.request = null;
      const runQueuedRefresh = this.refreshQueued && this.started && !document.hidden;
      const queuedMonths = this.monthsRefreshQueued;
      this.refreshQueued = false;
      this.monthsRefreshQueued = false;
      if (runQueuedRefresh) void this.refresh({ refreshMonths: queuedMonths });
    }
  }

  selectMonth(month: string): void {
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month) || month === this.selectedMonth) return;
    this.selectionVersion += 1;
    this.selectedMonth = month;
    this.page = 1;
    void this.refresh();
  }

  setSearch(value: string): void {
    this.search = value;
    this.page = 1;
  }

  setKindFilter(value: KindFilter): void {
    this.kindFilter = value;
    this.page = 1;
  }

  setAccountFilter(value: string): void {
    this.accountFilter = value;
    this.page = 1;
  }

  setPage(value: number): void {
    this.page = Math.max(1, Math.trunc(value));
  }

  setActiveSection(value: DashboardSection): void {
    this.activeSection = value;
  }

  async runAnalysis(): Promise<void> {
    if (this.analysisRequest) return this.analysisRequest;
    if (this.analysis.busy || !this.selectedMonth) return;
    const task = this.performAnalysis(this.selectedMonth);
    this.analysisRequest = task;
    try {
      await task;
    } finally {
      this.analysisRequest = null;
    }
  }

  private publishAnalysis(status: AnalysisStatus, version: number): void {
    if (!analysisStatusCanPublish(
      this.analysis,
      status,
      this.analysisVersion,
      version,
    )) return;
    this.analysis = status;
  }

  private failedAnalysis(month: string, code: string, message: string): AnalysisStatus {
    return {
      ...IDLE_ANALYSIS,
      state: "failed",
      window: `single month: ${month}`,
      error: { code, message },
    };
  }

  private async performAnalysis(month: string): Promise<void> {
    this.analysisVersion += 1;
    const version = this.analysisVersion;
    this.analysisLaunching = true;
    const launchController = new AbortController();
    let activeController = launchController;
    this.analysisAbortController = launchController;
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      launchController.abort();
    }, ANALYSIS_CLIENT_TIMEOUT_MS);
    try {
      const result = await startAnalysis(month, launchController.signal);
      this.publishAnalysis(result.analysis, version);
    } catch (requestError) {
      if (!this.started && requestError instanceof DOMException && requestError.name === "AbortError") return;
      const fromResponse = requestError instanceof DashboardApiError
        ? analysisStatusFromPayload(requestError.payload)
        : null;
      if (fromResponse) {
        this.publishAnalysis(fromResponse, version);
        return;
      }
      let recovered: AnalysisStatus | null = null;
      const recoveryController = new AbortController();
      activeController = recoveryController;
      this.analysisAbortController = recoveryController;
      const recoveryTimeout = setTimeout(() => {
        recoveryController.abort();
      }, ANALYSIS_STATUS_TIMEOUT_MS);
      try {
        recovered = await fetchAnalysisStatus(recoveryController.signal);
      } catch {
        recovered = null;
      } finally {
        clearTimeout(recoveryTimeout);
      }
      if (!analysisRecoveryOwnsLifecycle(
        this.started,
        this.analysisVersion,
        version,
      )) return;
      if (recovered && recovered.state !== "idle") {
        this.publishAnalysis(recovered, version);
        return;
      }
      const message = requestError instanceof Error
        ? requestError.message
        : "";
      this.publishAnalysis(
        this.failedAnalysis(
          month,
          timedOut ? "analysis_client_timeout" : "analysis_request_failed",
          timedOut ? "" : message,
        ),
        version,
      );
    } finally {
      clearTimeout(timeout);
      if (this.analysisAbortController === activeController) {
        this.analysisAbortController = null;
      }
      if (version === this.analysisVersion) this.analysisLaunching = false;
    }
  }

  private async performRefresh(refreshMonths: boolean): Promise<void> {
    this.abortController = new AbortController();
    const signal = this.abortController.signal;
    let refreshTimedOut = false;
    const refreshTimeout = setTimeout(() => {
      refreshTimedOut = true;
      this.abortController?.abort();
    }, REFRESH_TIMEOUT_MS);
    const hadData = this.book !== null;
    this.refreshing = hadData;

    let requestedMonth = this.selectedMonth || this.currentMonth;
    let requestedSelectionVersion = this.selectionVersion;
    try {
      if (refreshMonths || !this.selectedMonth) {
        const index = await fetchMonths(signal);
        this.months = [...index.months];
        this.currentMonth = index.current_month;
        if (!this.selectedMonth) {
          this.selectionVersion += 1;
          this.selectedMonth = index.current_month;
          requestedSelectionVersion = this.selectionVersion;
        }
        if (this.selectedMonth && !this.months.includes(this.selectedMonth)) {
          this.months = [...this.months, this.selectedMonth].sort();
        }
      }

      requestedMonth = this.selectedMonth || this.currentMonth;
      requestedSelectionVersion = this.selectionVersion;
      if (!requestedMonth) throw new Error("The server did not provide a current month.");
      const nextBook = await fetchBook(requestedMonth, signal);
      if (requestOwnsSelection(
        this.selectionVersion,
        this.selectedMonth,
        requestedSelectionVersion,
        requestedMonth,
      )) {
        this.book = nextBook;
        this.error = null;
      }

      try {
        const analysisVersion = this.analysisVersion;
        const nextAnalysis = await fetchAnalysisStatus(signal);
        this.publishAnalysis(nextAnalysis, analysisVersion);
      } catch (analysisError) {
        if (analysisError instanceof DOMException && analysisError.name === "AbortError") throw analysisError;
      }
    } catch (requestError) {
      const aborted = requestError instanceof DOMException && requestError.name === "AbortError";
      if (
        refreshFailureShouldPublish(aborted, refreshTimedOut)
        && requestOwnsSelection(
          this.selectionVersion,
          this.selectedMonth,
          requestedSelectionVersion,
          requestedMonth,
        )
      ) {
        const code = requestError instanceof DashboardApiError ? requestError.code : null;
        this.error = dashboardLoadErrorFrom(code);
        if (this.book && requestedMonth && requestedMonth !== this.book.dashboard_month) {
          this.selectionVersion += 1;
          this.selectedMonth = this.book.dashboard_month;
        }
      }
    } finally {
      clearTimeout(refreshTimeout);
      this.abortController = null;
      this.initialLoading = false;
      this.refreshing = false;
    }
  }
}

export const dashboardController = new DashboardController();
