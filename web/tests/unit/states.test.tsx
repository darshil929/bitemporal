import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { Banner } from "@/components/layout/Banner";
import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorState } from "@/components/layout/ErrorState";
import { NotFound } from "@/components/layout/NotFound";
import { Refetch } from "@/components/layout/Refetch";
import { Skeleton } from "@/components/layout/Skeleton";

afterEach(cleanup);

test("a skeleton takes the shape it is given and is hidden from assistive technology", () => {
  const { container } = render(<Skeleton className="h-4 w-[260px]" />);

  const block = container.firstElementChild;
  expect(block?.getAttribute("aria-hidden")).toBe("true");
  expect(block?.className.split(" ")).toEqual(
    expect.arrayContaining(["h-4", "w-[260px]", "rounded-xs", "bg-border"]),
  );
  expect(block?.className.split(" ")).not.toContain("h-3");
});

test.each([
  [true, true],
  [false, false],
])("a refetch held is %s busy and dimmed", (isRefetching, dimmed) => {
  const { container } = render(
    <Refetch isRefetching={isRefetching}>
      <p>Previous result</p>
    </Refetch>,
  );

  const region = container.firstElementChild;
  expect(region?.getAttribute("aria-busy")).toBe(String(isRefetching));
  expect(
    screen
      .getByText("Previous result")
      .parentElement?.classList.contains("opacity-50"),
  ).toBe(dimmed);
});

test("an empty state says what is missing and offers the way forward", () => {
  render(
    <EmptyState
      title="No instruments in the watchlist"
      text="Instruments added here get a daily change and an optional alert."
      action={<button type="button">Add instrument</button>}
    />,
  );

  expect(screen.getByText("No instruments in the watchlist")).toBeDefined();
  expect(screen.getByRole("button", { name: "Add instrument" })).toBeDefined();
});

test("an error state names the failure and retries on request", () => {
  const onRetry = vi.fn();
  render(
    <ErrorState
      title="The watchlist could not be loaded"
      text="Figures shown elsewhere on the page are unaffected."
      onRetry={onRetry}
    />,
  );

  expect(screen.getByRole("alert").textContent).toContain(
    "The watchlist could not be loaded",
  );
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(onRetry).toHaveBeenCalledOnce();
});

test("a missing instrument is named by the ISIN asked for, with the likely reason", () => {
  render(
    <NotFound isin="INE296A01024" action={<a href="/screener">Screener</a>} />,
  );

  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
    "No instrument with ISIN INE296A01024",
  );
  expect(
    screen.getByText(/a split or consolidation issues a new ISIN/i),
  ).toBeDefined();
  expect(screen.getByRole("link", { name: "Screener" })).toBeDefined();
});

test.each([
  ["flag", ["border-flag-border", "bg-flag-surface"], "text-flag"],
  ["neutral", ["border-border", "bg-surface-sunken"], "text-text-muted"],
] as const)("a %s banner draws in its own colours", (tone, surface, ink) => {
  const { container } = render(
    <Banner tone={tone}>NSE 31 Dec 2025 did not pass validation.</Banner>,
  );

  const banner = container.firstElementChild;
  expect(banner?.className.split(" ")).toEqual(
    expect.arrayContaining([...surface]),
  );
  expect(banner?.querySelector("svg")?.getAttribute("class")).toContain(ink);
  expect(banner?.textContent).toBe("NSE 31 Dec 2025 did not pass validation.");
});
