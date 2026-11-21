import type { components } from "@/lib/api";
import { failureText } from "@/lib/data-status";
import {
  formatCount,
  formatDayRange,
  formatSpan,
  formatTimeRange,
} from "@/lib/format";

export type RecordedRun = components["schemas"]["RecordedRunResponse"];
export type DailySourceKey =
  "bse_bhavcopy" | "nse_bhavcopy" | "bse_delivery" | "nse_delivery";

const FLOW_NAMES: Record<RecordedRun["flow"], string> = {
  sync: "Sync",
  bootstrap: "History load",
};

export const DAILY_SOURCES: readonly [DailySourceKey, string][] = [
  ["bse_bhavcopy", "BSE prices"],
  ["nse_bhavcopy", "NSE prices"],
  ["bse_delivery", "BSE delivery"],
  ["nse_delivery", "NSE delivery"],
];

const DAILY_FIELDS: readonly [string, string, boolean][] = [
  ["published", "Published", false],
  ["unpublished", "Not published", false],
  ["outside_coverage", "Outside coverage", false],
  ["failed", "Failed", true],
  ["rechecked", "Rechecked", false],
  ["corrected", "Corrected", false],
  ["recheck_failed", "Recheck failed", true],
];

const OTHER_SOURCES: readonly [string, string, string, string][] = [
  ["corporate_actions", "BSE corporate actions", "ranges", "year"],
  ["nse_corporate_actions", "NSE corporate actions", "ranges", "year"],
  ["bse_instrument_names", "BSE lists", "lists", "list"],
  ["nse_instrument_names", "NSE lists", "lists", "list"],
];

const SOURCE_LABELS: Readonly<Record<string, string>> = Object.fromEntries([
  ...DAILY_SOURCES,
  ...OTHER_SOURCES.map(([key, label]) => [key, label] as const),
]);

export const OUTCOME_WORDS: Record<RecordedRun["outcome"], string> = {
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const flowName = (run: RecordedRun): string => FLOW_NAMES[run.flow];
export const sourceLabel = (source: string): string =>
  SOURCE_LABELS[source] ?? source;
export const runHeading = (run: RecordedRun | null): string =>
  run?.flow === "bootstrap" ? "Last history load" : "Last sync";

/** One sentence placing a run: its days, start to end in India time, duration, and requester. */
export function runSummary(run: RecordedRun): string {
  const origin = run.requested_by
    ? `Started by ${run.requested_by}.`
    : "Started from the command line.";
  return `${formatDayRange(run.first_day, run.last_day)}. ${formatTimeRange(run.started_at, run.ended_at)}, ${formatSpan(run.duration_seconds)}. ${origin}`;
}

/** The daily-file counts of a run: one row per count, one value per daily source. */
export function dailyCountRows(run: RecordedRun) {
  return DAILY_FIELDS.map(([key, label, isFailure]) => ({
    key,
    label,
    isFailure,
    values: Object.fromEntries(
      DAILY_SOURCES.map(([src]) => [src, run.counts[src]?.[key] ?? null]),
    ) as Readonly<Record<DailySourceKey, number | null>>,
  }));
}

/** The corporate action and list reads of a run, omitting sources absent from its counts. */
export function otherSourceRows(run: RecordedRun) {
  return OTHER_SOURCES.flatMap(([key, source, unitKey, unit]) => {
    const entry = run.counts[key];
    if (!entry) return [];
    const count = entry[unitKey];
    const read =
      count === undefined
        ? null
        : `${formatCount(count)} ${unit}${count === 1 ? "" : "s"}`;
    return [{ key, source, read, failed: entry.failed ?? null }];
  });
}

/** The checks of a run: `162 passed, 1 warned, 0 failed`. */
export function checksLine(run: RecordedRun): string {
  return (
    `${formatCount(run.checks_passed)} passed, ${formatCount(run.warned_checks.length)} warned, ` +
    `${formatCount(run.failed_checks.length)} failed`
  );
}

/** What a run's row says beside its outcome: why it failed, or the checks that warned. */
export function runDetail(run: RecordedRun): string {
  if (run.outcome === "failed") {
    return failureText({
      failed_stages: run.failed_stages,
      failed_checks: run.failed_checks.length,
      failed_fetches: run.failures.length,
    });
  }
  const warned = run.warned_checks.length;
  return warned === 0
    ? ""
    : `${formatCount(warned)} ${warned === 1 ? "check" : "checks"} warned`;
}

/** Who started a run: the admin who asked for it, or the command line. */
export function startedBy(run: RecordedRun): string {
  return run.requested_by ?? "Command line";
}
