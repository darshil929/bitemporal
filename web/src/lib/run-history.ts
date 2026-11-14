import type { components } from "@/lib/api";
import { failureText } from "@/lib/data-status";
import { formatCount } from "@/lib/format";

export type RecordedRun = components["schemas"]["RecordedRunResponse"];

const FLOW_NAMES: Record<RecordedRun["flow"], string> = {
  sync: "Sync",
  bootstrap: "History load",
};

export const OUTCOME_WORDS: Record<RecordedRun["outcome"], string> = {
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function flowName(run: RecordedRun): string {
  return FLOW_NAMES[run.flow];
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
