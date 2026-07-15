import type {
  AnalysisStartResponse,
  AnalysisStatus,
  BookResponse,
  MonthIndex,
} from "$lib/types";

export class DashboardApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    readonly payload: unknown,
  ) {
    super("Dashboard request failed");
    this.name = "DashboardApiError";
  }
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    cache: "no-store",
    credentials: "same-origin",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const record = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
    const code = typeof record.error === "string"
      ? record.error
      : response.status === 409
        ? "unsupported_static_schema"
        : response.status === 422
          ? "invalid_static_ledger"
          : "dashboard_unavailable";
    throw new DashboardApiError(code, response.status, payload);
  }
  return payload as T;
}

export function fetchMonths(signal?: AbortSignal): Promise<MonthIndex> {
  return requestJson<MonthIndex>("/api/months", { signal });
}

export function fetchBook(month: string, signal?: AbortSignal): Promise<BookResponse> {
  return requestJson<BookResponse>(`/api/book?month=${encodeURIComponent(month)}`, { signal });
}

export function fetchAnalysisStatus(signal?: AbortSignal): Promise<AnalysisStatus> {
  return requestJson<AnalysisStatus>("/api/analyze/status", { signal });
}

export function startAnalysis(month: string, signal?: AbortSignal): Promise<AnalysisStartResponse> {
  return requestJson<AnalysisStartResponse>("/api/analyze", {
    method: "POST",
    signal,
    body: JSON.stringify({
      window: `single month: ${month}`,
      delivery: "dashboard only",
      output_filename: `analysis-${month}.html`,
    }),
  });
}
