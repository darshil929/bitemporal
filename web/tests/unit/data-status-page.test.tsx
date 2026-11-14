import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import DataStatusPage from "@/app/(app)/data/page";
import { formatSpan } from "@/lib/format";

const person = vi.hoisted(() => ({ role: "admin" }));

vi.mock("@/lib/page-access", () => ({
  requireSession: async () => ({ ...person, display_name: "Meera" }),
}));

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("not found");
  },
}));

const RUN = {
  run_id: "run-1",
  flow: "sync",
  first_day: "2026-11-08",
  last_day: "2026-11-14",
  started_at: "2026-11-14 10:50:47+00:00",
  ended_at: "2026-11-14 11:12:05+00:00",
  duration_seconds: 1278,
  outcome: "succeeded",
  counts: {},
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

const FAILED = {
  ...RUN,
  run_id: "run-0",
  outcome: "failed",
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

test("an admin reads the day the pages show and the newest runs", async () => {
  person.role = "admin";
  render(await DataStatusPage());

  expect(
    screen.getByRole("heading", { name: "Figures for 13 Nov 2026" }),
  ).toBeTruthy();
  expect(screen.getByText("5,389")).toBeTruthy();
  expect(screen.getByText("13 Nov 2026, complete, 4,690 bars")).toBeTruthy();
  const [, synced, failed] = screen.getAllByRole("row");
  expect(within(synced).getByText("21 min 18 s")).toBeTruthy();
  expect(within(synced).getByText("1 check warned")).toBeTruthy();
  expect(within(synced).getByText("Command line")).toBeTruthy();
  expect(within(failed).getByText("The models step failed")).toBeTruthy();
  expect(within(failed).getByText("Meera")).toBeTruthy();
  expect(
    screen.getByText("The last ten runs: 2 recorded. Times in India time"),
  ).toBeTruthy();
});

test("anyone but an admin finds no page", async () => {
  person.role = "member";

  await expect(DataStatusPage()).rejects.toThrow("not found");
});
