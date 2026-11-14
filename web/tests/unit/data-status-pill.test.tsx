import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { QueryProvider } from "@/components/layout/QueryProvider";
import { DataStatusPill } from "@/components/status/DataStatusPill";
import { type DataStatus, factRows } from "@/lib/data-status";

// The client takes fetch and Request when created, so both are replaced before it loads.
const fetchMock = vi.hoisted(() => {
  class PageRequest extends Request {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(
        typeof input === "string"
          ? new URL(input, window.location.href)
          : input,
        init,
      );
    }
  }
  vi.stubGlobal("Request", PageRequest);
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  vi.stubGlobal("fetch", mock);
  return mock;
});

beforeEach(() => fetchMock.mockReset());
afterEach(cleanup);

const FAILED: DataStatus = {
  state: "failed",
  published_day: "2026-11-09",
  venues: [
    { venue: "BSE", latest_day: "2026-11-09", is_complete: true, bars: 4683 },
    { venue: "NSE", latest_day: "2026-11-09", is_complete: true, bars: 2347 },
  ],
  last_run: {
    flow: "sync",
    first_day: "2026-11-03",
    last_day: "2026-11-09",
    started_at: "2026-11-09 14:30:16+00:00",
    ended_at: "2026-11-09 15:01:23+00:00",
    outcome: "failed",
    checks_passed: 162,
    failed_steps: ["dbt_models"],
    failed_stages: ["models"],
    failed_fetches: 0,
    failed_checks: 0,
    warned_checks: 1,
  },
  stale_since: null,
  days_never_asked: 2,
  running: null,
};

function answering(status: DataStatus): void {
  fetchMock.mockImplementation(async (request) => {
    const body = request?.url.endsWith("/data/runs")
      ? {
          runs: [],
          days_never_asked: [
            { first_day: "2026-10-03", last_day: "2026-10-04" },
          ],
        }
      : status;
    return new Response(JSON.stringify(body), {
      headers: { "Content-Type": "application/json" },
    });
  });
}

test("days never asked for are listed to an admin as runs of days", () => {
  expect(
    factRows(FAILED, true, [
      { first_day: "2026-10-03", last_day: "2026-10-04" },
      { first_day: "2026-10-11", last_day: "2026-10-11" },
    ])[4],
  ).toEqual({
    label: "Days never asked for",
    value: "2: 3 to 4 Oct 2026, 11 Oct 2026",
    detail: "No daily file was asked for these days",
    flagged: true,
  });
});

test("the pill opens the facts, and links an admin to the run that failed", async () => {
  answering(FAILED);
  render(
    <QueryProvider>
      <DataStatusPill isAdmin />
    </QueryProvider>,
  );

  const pill = await screen.findByRole("button", { name: /Failed, 9 Nov/ });
  fireEvent.click(pill);

  expect(await screen.findByText("Figures for 9 Nov 2026")).toBeTruthy();
  expect(screen.getByText("The models step failed")).toBeTruthy();
  expect(await screen.findByText("2: 3 to 4 Oct 2026")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Open the run" }).getAttribute("href"),
  ).toBe("/data");
});

test("a member reads the state without the failed step or a link", async () => {
  answering(FAILED);
  render(
    <QueryProvider>
      <DataStatusPill isAdmin={false} />
    </QueryProvider>,
  );

  fireEvent.click(await screen.findByRole("button", { name: /Failed, 9 Nov/ }));

  expect(await screen.findByText("Figures for 9 Nov 2026")).toBeTruthy();
  expect(screen.queryByText("The models step failed")).toBeNull();
  expect(screen.queryByRole("link")).toBeNull();
  expect(
    fetchMock.mock.calls.some(([request]) =>
      request.url.endsWith("/data/runs"),
    ),
  ).toBe(false);
});
