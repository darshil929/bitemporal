import { expect, test } from "vitest";

import { type DataStatus, factRows, pillText } from "@/lib/data-status";
import { formatDayRange, formatWeekday } from "@/lib/format";

const RUN: NonNullable<DataStatus["last_run"]> = {
  flow: "sync",
  first_day: "2026-11-03",
  last_day: "2026-11-09",
  started_at: "2026-11-09 14:30:16+00:00",
  ended_at: "2026-11-09 15:01:23+00:00",
  outcome: "succeeded",
  checks_passed: 162,
  failed_steps: [],
  failed_stages: [],
  failed_fetches: 0,
  failed_checks: 0,
  warned_checks: 1,
};

const FRESH: DataStatus = {
  state: "fresh",
  published_day: "2026-11-09",
  venues: [
    { venue: "BSE", latest_day: "2026-11-09", is_complete: true, bars: 4683 },
    { venue: "NSE", latest_day: "2026-11-09", is_complete: true, bars: 2347 },
  ],
  last_run: RUN,
  stale_since: null,
  days_never_asked: 0,
  running: null,
};

const FAILED: DataStatus = {
  ...FRESH,
  state: "failed",
  last_run: {
    ...RUN,
    outcome: "failed",
    failed_steps: ["dbt_models"],
    failed_stages: ["models"],
  },
};

function labels(rows: ReturnType<typeof factRows>): string[] {
  return rows.map((row) => row.label);
}

test("days read as a run and with their weekday", () => {
  expect(formatDayRange("2026-11-04", "2026-11-10")).toBe("4 to 10 Nov 2026");
  expect(formatDayRange("2026-09-28", "2026-10-04")).toBe(
    "28 Sep to 4 Oct 2026",
  );
  expect(formatDayRange("2025-12-29", "2026-01-04")).toBe(
    "29 Dec 2025 to 4 Jan 2026",
  );
  expect(formatDayRange("2026-11-10", "2026-11-10")).toBe("10 Nov 2026");
  expect(formatWeekday("2026-10-12")).toBe("Mon 12 Oct 2026");
});

test("a fresh status names each venue's day, the last sync and its checks", () => {
  const rows = factRows(FRESH, true);

  expect(pillText(FRESH)).toBe("Fresh, 9 Nov");
  expect(labels(rows)).toEqual([
    "BSE latest day",
    "NSE latest day",
    "Last sync",
    "Sync running",
    "Days never asked for",
    "Next scheduled sync",
  ]);
  expect(rows[0].value).toBe("9 Nov 2026, complete, 4,683 bars");
  expect(rows[2]).toEqual({
    label: "Last sync",
    value: "9 Nov 2026, 20:31, succeeded",
    detail: "For 3 to 9 Nov 2026. Checks 162 passed, 1 warned, 0 failed",
    flagged: false,
  });
});

test("a failure is named to an admin and leads the facts", () => {
  const [admin] = factRows(FAILED, true);
  const member = factRows(FAILED, false);

  expect(admin).toMatchObject({
    value: "9 Nov 2026, 20:31, failed",
    detail: "The models step failed",
    flagged: true,
  });
  expect(member[0].detail).toBeUndefined();
  expect(labels(member)).not.toContain("Days never asked for");
});

test("a stale status names the weekday without figures", () => {
  const stale: DataStatus = {
    ...FRESH,
    state: "stale",
    stale_since: "2026-11-11",
  };

  expect(factRows(stale, true)[0]).toEqual({
    label: "No figures for",
    value: "Wed 11 Nov 2026",
    detail: "Its morning sync time, 07:30, has passed",
    flagged: true,
  });
});

test("a sync running names its days, stage and the time left", () => {
  const updating: DataStatus = {
    ...FRESH,
    state: "updating",
    running: {
      flow: "sync",
      first_day: "2026-11-08",
      last_day: "2026-11-14",
      status: "running",
      requested_at: "2026-11-14 15:00:00+00:00",
      started_at: "2026-11-14 15:00:20+00:00",
      current_stage: "models",
      time_left: { seconds: 840, minutes: 14 },
    },
  };

  expect(factRows(updating, true)[2]).toEqual({
    label: "Sync running",
    value: "8 to 14 Nov 2026, started 14 Nov 2026, 20:30",
    detail: "Models, about 14 min left",
    flagged: false,
  });
});

test("days never asked for are counted to an admin", () => {
  const gaps: DataStatus = { ...FRESH, days_never_asked: 1 };

  expect(factRows(gaps, true)[4]).toEqual({
    label: "Days never asked for",
    value: "1",
    detail: "No daily file was asked for this day",
    flagged: true,
  });
});

test("an installation with no run has no figures and no sync", () => {
  const unknown: DataStatus = {
    ...FRESH,
    state: "unknown",
    published_day: null,
    venues: [],
    last_run: null,
  };
  const rows = factRows(unknown, true);

  expect(pillText(unknown)).toBe("Unknown");
  expect(rows[0].value).toBe("—");
  expect(rows[2].value).toBe("No sync recorded");
});
