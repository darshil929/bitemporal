import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { LastSyncCard } from "@/app/(app)/data/LastSyncCard";
import DataStatusPage from "@/app/(app)/data/page";
import { formatSpan } from "@/lib/format";
import type { RecordedRun } from "@/lib/run-history";

const person = vi.hoisted(() => ({ role: "admin" }));

vi.mock("@/lib/page-access", () => ({
  requireSession: async () => ({ ...person, display_name: "Meera" }),
}));

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("not found");
  },
}));

const DAILY = {
  published: 5,
  unpublished: 2,
  outside_coverage: 0,
  failed: 0,
  rechecked: 2,
  corrected: 0,
  recheck_failed: 0,
};

const RUN: RecordedRun = {
  run_id: "run-1",
  flow: "sync",
  first_day: "2026-11-08",
  last_day: "2026-11-14",
  started_at: "2026-11-14T10:50:47+00:00",
  ended_at: "2026-11-14T11:12:05+00:00",
  duration_seconds: 1278,
  outcome: "succeeded",
  counts: {
    bse_bhavcopy: DAILY,
    nse_bhavcopy: {
      published: 5,
      unpublished: 2,
      outside_coverage: 0,
      failed: 0,
    },
    bse_delivery: DAILY,
    nse_delivery: DAILY,
    corporate_actions: { ranges: 28, failed: 0 },
    nse_corporate_actions: { ranges: 33, failed: 0 },
    bse_instrument_names: { lists: 3, failed: 0 },
    nse_instrument_names: { lists: 2, failed: 0 },
  },
  checks_passed: 170,
  failures: [],
  warned_checks: [
    { name: "assert_capital_actions_reported_by_both_venues", rows: 17 },
  ],
  failed_checks: [],
  failed_steps: [],
  failed_stages: [],
  unmaterialized: [],
  requested_by: null,
};

const FAILED: RecordedRun = {
  ...RUN,
  run_id: "run-0",
  outcome: "failed",
  counts: {
    ...RUN.counts,
    bse_bhavcopy: { ...DAILY, failed: 1 },
    corporate_actions: { ranges: 28, failed: 1 },
  },
  failures: [
    { source: "corporate_actions", key: "2026", detail: "29 actions missing" },
  ],
  failed_checks: [{ name: "assert_venue_closes_agree", rows: 1 }],
  failed_steps: ["dbt_models"],
  failed_stages: ["models"],
  requested_by: "Meera",
};

vi.mock("@/lib/server-api-client", () => ({
  serverApiClient: async () => ({
    GET: async (path: string) => ({
      data:
        path === "/data/runs"
          ? {
              runs: [RUN, FAILED],
              days_never_asked: [],
              published_instruments: 5389,
            }
          : {
              state: "fresh",
              published_day: "2026-11-13",
              venues: [
                {
                  venue: "BSE",
                  latest_day: "2026-11-13",
                  is_complete: true,
                  bars: 4690,
                },
                {
                  venue: "NSE",
                  latest_day: "2026-11-13",
                  is_complete: true,
                  bars: 2351,
                },
              ],
              last_run: null,
              stale_since: null,
              days_never_asked: 0,
              running: null,
            },
    }),
  }),
}));

afterEach(cleanup);

test("a run's length reads in minutes and seconds", () => {
  expect(formatSpan(0.4)).toBe("under 1 s");
  expect(formatSpan(45)).toBe("45 s");
  expect(formatSpan(1278)).toBe("21 min 18 s");
});

test("an admin reads the day the pages show, the latest run report, and the newest runs", async () => {
  person.role = "admin";
  render(await DataStatusPage());

  expect(
    screen.getByRole("heading", { name: "Figures for 13 Nov 2026" }),
  ).toBeTruthy();
  expect(screen.getByText("5,389")).toBeTruthy();
  expect(screen.getByText("13 Nov 2026, complete, 4,690 bars")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Last sync" })).toBeTruthy();
  expect(
    screen.getByText(
      "8 to 14 Nov 2026. 14 Nov 2026, 16:20 to 16:42, 21 min 18 s. Started from the command line.",
    ),
  ).toBeTruthy();
  const recheckedRow = within(
    screen.getByRole("table", {
      name: "Daily file counts from the latest run",
    }),
  )
    .getByText("Rechecked")
    .closest("tr") as HTMLTableRowElement;
  expect(within(recheckedRow).getAllByText("2")).toHaveLength(3);
  expect(within(recheckedRow).getByText("—")).toBeTruthy();
  const otherTable = screen.getByRole("table", {
    name: "Corporate action and list reads from the latest run",
  });
  expect(within(otherTable).getByText("28 years")).toBeTruthy();
  expect(within(otherTable).getByText("3 lists")).toBeTruthy();
  expect(
    screen.getByText("assert_capital_actions_reported_by_both_venues"),
  ).toBeTruthy();
  expect(screen.getByText("17 rows")).toBeTruthy();
  const [, synced, failed] = within(
    screen.getByRole("table", { name: "The newest runs of the flows" }),
  ).getAllByRole("row");
  expect(within(synced).getByText("21 min 18 s")).toBeTruthy();
  expect(within(synced).getByText("1 check warned")).toBeTruthy();
  expect(within(synced).getByText("Command line")).toBeTruthy();
  expect(within(failed).getByText("The models step failed")).toBeTruthy();
  expect(within(failed).getByText("Meera")).toBeTruthy();
  expect(
    screen.getByText("The last ten runs: 2 recorded. Times in India time"),
  ).toBeTruthy();
});

test("the latest run report flags failed counts, failed fetches, failed checks, and names its requester", () => {
  render(<LastSyncCard run={{ ...FAILED, flow: "bootstrap" }} />);
  expect(
    screen.getByRole("heading", { name: "Last history load" }),
  ).toBeTruthy();
  expect(screen.getByText(/Started by Meera\.$/)).toBeTruthy();
  expect(screen.getByText("The models step failed")).toBeTruthy();
  expect(screen.getByText("29 actions missing")).toBeTruthy();
  expect(screen.getByText("assert_venue_closes_agree")).toBeTruthy();
  expect(screen.getByText("1 row")).toBeTruthy();
  const failedRow = within(
    screen.getByRole("table", {
      name: "Daily file counts from the latest run",
    }),
  )
    .getByText("Failed")
    .closest("tr") as HTMLTableRowElement;
  expect(within(failedRow).getByText("1").className).toContain("text-flag");
});

test("the latest run card says no sync recorded when no run exists", () => {
  render(<LastSyncCard run={null} />);
  expect(screen.getByRole("heading", { name: "Last sync" })).toBeTruthy();
  expect(screen.getByText("No sync recorded")).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
});

test("anyone but an admin finds no page", async () => {
  person.role = "member";

  await expect(DataStatusPage()).rejects.toThrow("not found");
});
