import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { AppShell } from "@/components/layout/AppShell";
import { QueryProvider } from "@/components/layout/QueryProvider";
import { PageHeader } from "@/components/layout/PageHeader";

const location = vi.hoisted(() => ({ pathname: "/" }));

vi.mock("next/navigation", () => ({
  usePathname: () => location.pathname,
  useRouter: () => ({ push: vi.fn() }),
}));

afterEach(cleanup);

const ADMIN = {
  id: 1,
  username: "darshil929",
  display_name: "Darshil Thakkar",
  role: "admin",
  must_change_password: false,
} as const;

function shellAt(pathname: string) {
  location.pathname = pathname;
  render(
    <QueryProvider>
      <AppShell person={ADMIN}>
        <p>Page</p>
      </AppShell>
    </QueryProvider>,
  );
}

test("the shell links every page and holds the page in its main region", () => {
  shellAt("/");

  const links = screen.getAllByRole("link");
  expect(
    links.map((link) => [link.textContent, link.getAttribute("href")]),
  ).toEqual([
    ["Dashboard", "/"],
    ["Screener", "/screener"],
    ["Watchlist", "/watchlist"],
  ]);
  expect(screen.getByRole("main").textContent).toBe("Page");
});

test.each([
  ["/", "Dashboard"],
  ["/screener", "Screener"],
  ["/watchlist/core", "Watchlist"],
])("at %s the shell marks %s as the page open", (pathname, label) => {
  shellAt(pathname);

  expect(screen.getByRole("link", { current: "page" }).textContent).toBe(label);
});

test("the shell holds the instrument search, reached from anywhere with /", () => {
  shellAt("/");

  expect(
    screen.getByRole("combobox", { name: "Search instruments" }),
  ).toBeDefined();
  expect(screen.getByText("/").tagName).toBe("KBD");
});

test("a page outside the three marks none open", () => {
  shellAt("/instrument/INE040A01034");

  expect(screen.queryByRole("link", { current: "page" })).toBeNull();
});

test("a page header names the page and holds what sits beside the title", () => {
  render(<PageHeader title="Market" trailing={<span>9 Oct 2026</span>} />);

  expect(
    screen.getByRole("heading", { level: 1, name: "Market" }),
  ).toBeDefined();
  expect(screen.getByText("9 Oct 2026")).toBeDefined();
});
