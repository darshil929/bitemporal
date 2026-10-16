import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { QueryProvider } from "@/components/layout/QueryProvider";
import { apiClient, apiQueries } from "@/lib/api-client";
import {
  createQueryClient,
  retriesMarketData,
  STALE_AFTER_MS,
} from "@/lib/query";
import { serverApiClient } from "@/lib/server-api-client";

import nextConfig from "../../next.config";

// The clients take fetch and Request when created, so both are replaced before they load. The test
// DOM's Request is Node's, which wants a whole address where a browser reads a path against the
// page.
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

const incoming = vi.hoisted(() => ({ headers: new Headers() }));

vi.mock("next/headers", () => ({ headers: async () => incoming.headers }));

const HDFC_BANK = "INE040A01034";
const SIGNED_IN = "__Host-bitemporal_session=signed-in";

beforeEach(() => {
  fetchMock.mockReset();
  incoming.headers = new Headers();
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

function answer(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function requested(): Request {
  const [request] = fetchMock.mock.lastCall ?? [];
  expect(request).toBeDefined();
  return request as Request;
}

test("the browser asks the web app's own address for an instrument's day", async () => {
  fetchMock.mockResolvedValueOnce(answer({ isin: HDFC_BANK, close: 1570.4 }));

  const { data } = await apiClient.GET("/instruments/{isin}/day", {
    params: { path: { isin: HDFC_BANK }, query: { venue: "NSE" } },
  });

  expect(requested().url).toBe(
    `http://localhost:3000/api/instruments/${HDFC_BANK}/day?venue=NSE`,
  );
  expect(data?.close).toBe(1570.4);
});

test("a page asks the API's own address with the cookies of the request it answers", async () => {
  vi.stubEnv("API_URL", "http://api:8000");
  incoming.headers = new Headers({ cookie: SIGNED_IN });
  fetchMock.mockResolvedValueOnce(answer({ isin: HDFC_BANK }));

  const client = await serverApiClient();
  await client.GET("/instruments/{isin}", {
    params: { path: { isin: HDFC_BANK } },
  });

  expect(requested().url).toBe(`http://api:8000/instruments/${HDFC_BANK}`);
  expect(requested().headers.get("cookie")).toBe(SIGNED_IN);
});

test("a page answering a request with no cookies sends none, to the local API by default", async () => {
  fetchMock.mockResolvedValueOnce(answer({ published_day: "2026-10-15" }));

  const client = await serverApiClient();
  await client.GET("/market/day");

  expect(requested().url).toBe("http://localhost:8000/market/day");
  expect(requested().headers.get("cookie")).toBeNull();
});

test("the web app forwards its /api paths to the API's own address", async () => {
  vi.stubEnv("API_URL", "http://api:8000");

  expect(await nextConfig.rewrites?.()).toEqual([
    { source: "/api/:path*", destination: "http://api:8000/:path*" },
  ]);
});

function PublishedDay() {
  const { data } = apiQueries.useQuery("get", "/market/day");
  return <p>{data ? data.published_day : "Loading"}</p>;
}

test("a component reads the published day through the query hooks", async () => {
  fetchMock.mockResolvedValueOnce(answer({ published_day: "2026-10-15" }));

  render(
    <QueryProvider>
      <PublishedDay />
    </QueryProvider>,
  );

  expect(await screen.findByText("2026-10-15")).toBeDefined();
  expect(requested().url).toBe("http://localhost:3000/api/market/day");
});

test("a read stays current for five minutes and is retried only while market data updates", () => {
  const updating = { detail: { reason: "market_data_updating" } };
  const defaults = createQueryClient().getDefaultOptions().queries;

  expect(STALE_AFTER_MS).toBe(300_000);
  expect(defaults?.staleTime).toBe(STALE_AFTER_MS);
  expect(defaults?.retry).toBe(retriesMarketData);
  expect(
    [0, 1, 2].map((failures) => retriesMarketData(failures, updating)),
  ).toEqual([true, true, false]);
  expect(
    retriesMarketData(0, { detail: { reason: "instrument_not_found" } }),
  ).toBe(false);
  expect(retriesMarketData(0, new TypeError("Failed to fetch"))).toBe(false);
});
