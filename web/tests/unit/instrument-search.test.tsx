import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { InstrumentSearch } from "@/components/controls/InstrumentSearch";
import { QueryProvider } from "@/components/layout/QueryProvider";

// The client takes fetch and Request when created, so both are replaced before it loads; the test
// DOM's Request wants a whole address where a browser reads a path against the page. The list
// measures itself and scrolls its chosen row into view, which the test DOM cannot.
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
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    },
  );
  Element.prototype.scrollIntoView = () => {};
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  vi.stubGlobal("fetch", mock);
  return mock;
});

const push = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const MATCHES = [
  {
    isin: "INE040A01034",
    display_name: "HDFC Bank Ltd",
    symbol: "HDFCBANK",
    venues: ["BSE", "NSE"],
  },
  {
    isin: "INE795G01014",
    display_name: "HDFC Life Insurance Company Ltd",
    symbol: "HDFCLIFE",
    venues: ["NSE"],
  },
];

beforeEach(() => {
  fetchMock.mockReset();
  push.mockReset();
});

afterEach(cleanup);

function answer(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function search(): HTMLElement {
  render(
    <QueryProvider>
      <InstrumentSearch shortcutKey="/" />
    </QueryProvider>,
  );
  return screen.getByRole("combobox", { name: "Search instruments" });
}

function type(field: HTMLElement, text: string) {
  fireEvent.focus(field);
  fireEvent.change(field, { target: { value: text } });
}

test("one character asks nothing; two ask for matches, each with its symbol and venues", async () => {
  fetchMock.mockResolvedValue(answer(MATCHES));
  const field = search();

  type(field, "h");
  await new Promise((settled) => setTimeout(settled, 300));
  expect(fetchMock).not.toHaveBeenCalled();

  type(field, "hd");
  const bank = await screen.findByRole("option", { name: /HDFC Bank Ltd/ });

  const [request] = fetchMock.mock.lastCall ?? [];
  expect(request?.url).toBe("http://localhost:3000/api/instruments?q=hd");
  expect(within(bank).getByText("HDFCBANK").classList).toContain("font-mono");
  expect(
    within(bank)
      .getAllByText(/^(BSE|NSE)$/)
      .map((venue) => venue.textContent),
  ).toEqual(["BSE", "NSE"]);
  expect(bank.getAttribute("aria-selected")).toBe("true");
});

test("down then enter opens the page of the instrument chosen", async () => {
  fetchMock.mockResolvedValue(answer(MATCHES));
  const field = search();
  type(field, "hdfc");
  await screen.findByRole("option", { name: /HDFC Life/ });

  fireEvent.keyDown(field, { key: "ArrowDown" });
  fireEvent.keyDown(field, { key: "Enter" });

  expect(push).toHaveBeenCalledWith("/instrument/INE795G01014");
});

test("a search finding nothing says so", async () => {
  fetchMock.mockResolvedValue(answer([]));
  type(search(), "zzz");

  expect(await screen.findByText("No instrument matches “zzz”")).toBeDefined();
});

test("a search that fails says search is unavailable", async () => {
  fetchMock.mockResolvedValue(
    answer({ detail: { reason: "not_signed_in" } }, 401),
  );
  type(search(), "hdfc");

  expect(await screen.findByText("Search is unavailable")).toBeDefined();
});

test("the shortcut moves focus to the search and escape closes its list", async () => {
  fetchMock.mockResolvedValue(answer(MATCHES));
  const field = search();

  fireEvent.keyDown(document.body, { key: "/" });
  expect(document.activeElement).toBe(field);

  type(field, "hdfc");
  await screen.findByRole("listbox");
  fireEvent.keyDown(field, { key: "Escape" });

  expect(screen.queryByRole("listbox")).toBeNull();
});
