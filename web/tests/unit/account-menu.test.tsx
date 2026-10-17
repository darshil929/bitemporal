import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AccountMenu } from "@/components/layout/AccountMenu";

// The client takes fetch and Request when created, so both are replaced before it loads; the test
// DOM's Request wants a whole address where a browser reads a path against the page.
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

// The menu measures its trigger as a browser does; the test DOM has no resize observer.
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  },
);

const PAGE = window.location;
const assign = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  assign.mockReset();
  vi.stubGlobal("location", {
    href: "http://localhost:3000/screener",
    pathname: "/screener",
    search: "",
    assign,
  });
});

afterEach(() => {
  cleanup();
  vi.stubGlobal("location", PAGE);
});

function openMenu(role: "admin" | "member", name: string) {
  render(
    <AccountMenu
      person={{ display_name: name, username: "darshil929", role }}
    />,
  );
  fireEvent.keyDown(screen.getByRole("button", { name }), { key: "Enter" });
}

test.each([
  ["admin", "Admin"],
  ["member", "Member"],
] as const)(
  "the menu names the %s signed in with their username and role, then Sign out",
  (role, words) => {
    openMenu(role, "Darshil Thakkar");

    const menu = screen.getByRole("menu");
    expect(menu.textContent).toBe(`Darshil Thakkardarshil929${words}Sign out`);
    expect(
      screen.getAllByRole("menuitem").map((item) => item.textContent),
    ).toEqual(["Sign out"]);
  },
);

test("signing out ends the session and opens sign-in, which says so", async () => {
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
  openMenu("admin", "Darshil Thakkar");

  fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));

  await waitFor(() =>
    expect(assign).toHaveBeenCalledWith("/sign-in?ended=signed_out"),
  );
  const [request] = fetchMock.mock.lastCall ?? [];
  expect(request?.method).toBe("POST");
  expect(request?.url).toBe("http://localhost:3000/api/auth/sign-out");
});

test("a sign-out that fails leaves the menu open, saying so", async () => {
  fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
  openMenu("member", "Darshil Thakkar");

  fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));

  expect((await screen.findByRole("alert")).textContent).toBe(
    "Sign-out is unavailable. Try again.",
  );
  expect(screen.getByRole("menu")).toBeDefined();
  expect(assign).not.toHaveBeenCalled();
});
