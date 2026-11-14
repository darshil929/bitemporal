import type { components } from "@/lib/api";
import {
  formatCount,
  formatDate,
  formatDateTime,
  formatDayRange,
  formatShortDate,
  formatWeekday,
} from "@/lib/format";

export type DataStatus = components["schemas"]["DataStatusResponse"];
export type DataState = DataStatus["state"];
type Stage = NonNullable<
  components["schemas"]["RunningSyncResponse"]["current_stage"]
>;
type DayStretch = components["schemas"]["DayStretchResponse"];

export type FactRow = Readonly<{
  label: string;
  value: string;
  detail?: string;
  flagged: boolean;
}>;

export const STATE_WORDS: Record<DataState, string> = {
  fresh: "Fresh",
  updating: "Updating",
  stale: "Stale",
  failed: "Failed",
  unknown: "Unknown",
};

const STAGE_WORDS: Record<Stage, string> = {
  prices: "prices",
  identity: "identity",
  delivery: "delivery",
  actions: "corporate actions",
  names: "names",
  models: "models",
  features: "features",
  checks: "checks",
};

// The morning sync runs at 07:30 India time, by when every file of the weekday before is due.
const FILES_DUE = "07:30";

export function isFlagged(state: DataState): boolean {
  return state === "stale" || state === "failed";
}

function capitalised(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The pill's words: the state, and the day the pages show where there is one. */
export function pillText({ state, published_day }: DataStatus): string {
  const word = STATE_WORDS[state];
  return published_day ? `${word}, ${formatShortDate(published_day)}` : word;
}

export function headline({ published_day }: DataStatus): string {
  return published_day
    ? `Figures for ${formatDate(published_day)}`
    : "No figures yet";
}

function venueRow(status: DataStatus, venue: "BSE" | "NSE"): FactRow {
  const held = status.venues.find((day) => day.venue === venue);
  const value = held
    ? `${formatDate(held.latest_day)}, ${held.is_complete ? "complete" : "partial"}, ${formatCount(held.bars)} bars`
    : "—";
  return { label: `${venue} latest day`, value, flagged: false };
}

function counted(count: number, noun: string): string {
  return `${formatCount(count)} ${noun}${count === 1 ? "" : "s"}`;
}

/** Why the last run failed: the stages that failed, else the checks and the fetches. */
export function failureText(run: NonNullable<DataStatus["last_run"]>): string {
  const stages = run.failed_stages.map((stage) => STAGE_WORDS[stage]);
  if (stages.length > 0) {
    return `The ${stages.join(" and ")} ${stages.length === 1 ? "step" : "steps"} failed`;
  }
  const checks =
    run.failed_checks > 0
      ? [`${counted(run.failed_checks, "check")} failed`]
      : [];
  const fetches =
    run.failed_fetches > 0
      ? [`${counted(run.failed_fetches, "file")} could not be read`]
      : [];
  return capitalised([...checks, ...fetches].join(", "));
}

function lastSyncRow(status: DataStatus, isAdmin: boolean): FactRow {
  const run = status.last_run;
  if (run === null) {
    return { label: "Last sync", value: "No sync recorded", flagged: false };
  }
  const ended = formatDateTime(run.ended_at);
  if (run.outcome === "failed") {
    return {
      label: "Last sync",
      value: `${ended}, failed`,
      detail: isAdmin ? failureText(run) : undefined,
      flagged: true,
    };
  }
  const failedChecks = run.failed_checks;
  return {
    label: "Last sync",
    value: `${ended}, succeeded`,
    detail:
      `For ${formatDayRange(run.first_day, run.last_day)}. Checks ${formatCount(run.checks_passed)} passed, ` +
      `${formatCount(run.warned_checks)} warned, ${formatCount(failedChecks)} failed`,
    flagged: false,
  };
}

function runningRow({ running }: DataStatus): FactRow {
  if (running === null) {
    return { label: "Sync running", value: "None", flagged: false };
  }
  const days = formatDayRange(running.first_day, running.last_day);
  if (running.started_at === null) {
    return {
      label: "Sync running",
      value: `${days}, requested ${formatDateTime(running.requested_at)}`,
      detail:
        running.status === "cancelling"
          ? "Cancelling"
          : "Starting within about 30 seconds",
      flagged: false,
    };
  }
  const stage = running.current_stage
    ? capitalised(STAGE_WORDS[running.current_stage])
    : null;
  const left = running.time_left
    ? `about ${running.time_left.minutes} min left`
    : null;
  const progress =
    running.status === "cancelling"
      ? "Cancelling"
      : [stage, left].filter(Boolean).join(", ");
  return {
    label: "Sync running",
    value: `${days}, started ${formatDateTime(running.started_at)}`,
    detail: progress || undefined,
    flagged: false,
  };
}

function stretchText({ first_day, last_day }: DayStretch): string {
  return first_day === last_day
    ? formatDate(first_day)
    : formatDayRange(first_day, last_day);
}

function neverAskedRow(
  status: DataStatus,
  stretches: readonly DayStretch[],
): FactRow {
  const count = status.days_never_asked;
  if (count === 0) {
    return { label: "Days never asked for", value: "0", flagged: false };
  }
  const days = stretches.map(stretchText).join(", ");
  return {
    label: "Days never asked for",
    value: days ? `${formatCount(count)}: ${days}` : formatCount(count),
    detail:
      count === 1
        ? "No daily file was asked for this day"
        : "No daily file was asked for these days",
    flagged: true,
  };
}

const NEXT_SYNC: FactRow = {
  label: "Next scheduled sync",
  value: "No scheduled sync",
  flagged: false,
};

/** The popover's rows, in the order each state draws them. An admin also reads why a run failed
 * and which days were never asked for. */
export function factRows(
  status: DataStatus,
  isAdmin: boolean,
  stretches: readonly DayStretch[] = [],
): FactRow[] {
  const venues = [venueRow(status, "BSE"), venueRow(status, "NSE")];
  const lastSync = lastSyncRow(status, isAdmin);
  const running = runningRow(status);
  const neverAsked = isAdmin ? [neverAskedRow(status, stretches)] : [];
  switch (status.state) {
    case "stale":
      return [
        {
          label: "No figures for",
          value: status.stale_since ? formatWeekday(status.stale_since) : "—",
          detail: `Its morning sync time, ${FILES_DUE}, has passed`,
          flagged: true,
        },
        ...venues,
        lastSync,
        running,
        NEXT_SYNC,
      ];
    case "failed":
      return [lastSync, ...venues, running, ...neverAsked, NEXT_SYNC];
    case "updating":
      return [...venues, running, lastSync, ...neverAsked, NEXT_SYNC];
    case "unknown":
      return [...venues, lastSync, running, NEXT_SYNC];
    default:
      return [...venues, lastSync, running, ...neverAsked, NEXT_SYNC];
  }
}
