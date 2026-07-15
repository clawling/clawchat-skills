import type { AnalysisStatus, DashboardLoadError } from "./types.js";

export function dashboardLoadErrorFrom(code: string | null): DashboardLoadError {
  if (code === "unsupported_static_schema") return "unsupported";
  if (code === "invalid_static_ledger") return "invalid";
  return "unavailable";
}

export function refreshFailureShouldPublish(aborted: boolean, timedOut: boolean): boolean {
  return !aborted || timedOut;
}

export function analysisRecoveryOwnsLifecycle(
  started: boolean,
  currentVersion: number,
  requestVersion: number,
): boolean {
  return started && currentVersion === requestVersion;
}

export function requestOwnsSelection(
  currentVersion: number,
  currentMonth: string,
  requestedVersion: number,
  requestedMonth: string,
): boolean {
  return currentVersion === requestedVersion && currentMonth === requestedMonth;
}

export function analysisStatusFromPayload(value: unknown): AnalysisStatus | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const candidate = record.analysis && typeof record.analysis === "object"
    ? record.analysis as Record<string, unknown>
    : record;
  if (
    !["idle", "running", "succeeded", "failed"].includes(String(candidate.state))
    || typeof candidate.busy !== "boolean"
    || typeof candidate.run_id !== "string"
  ) return null;
  return candidate as unknown as AnalysisStatus;
}

export function analysisStatusCanPublish(
  current: AnalysisStatus,
  next: AnalysisStatus,
  currentVersion: number,
  requestedVersion: number,
): boolean {
  if (currentVersion !== requestedVersion) return false;
  if (current.state === "idle") return true;
  if (!next.run_id || next.state === "idle") return false;
  if (!current.run_id) return true;

  if (next.run_id !== current.run_id) {
    return next.started_at > current.started_at;
  }

  const currentIsTerminal = ["succeeded", "failed"].includes(current.state);
  if (currentIsTerminal) return next.state === current.state;
  return next.state === "running" || ["succeeded", "failed"].includes(next.state);
}
