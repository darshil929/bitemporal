import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { NewPasswordForm } from "@/app/(signed-out)/sign-in/NewPasswordForm";
import SignInPage from "@/app/(signed-out)/sign-in/page";
import { SignInForm } from "@/app/(signed-out)/sign-in/SignInForm";
import { returnAddress } from "@/lib/return-address";

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

const navigation = vi.hoisted(() => ({
  replace: vi.fn(),
  redirect: vi.fn((to: string) => {
    throw new Error(`redirected to ${to}`);
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navigation.replace, refresh: () => {} }),
  redirect: navigation.redirect,
}));

const api = vi.hoisted(() => ({
  adminExists: true,
  session: null as unknown,
  ended: null as unknown,
}));

vi.mock("@/lib/server-api-client", () => ({
  serverApiClient: async () => ({
    GET: async (path: string) =>
      path === "/setup"
        ? { data: { admin_exists: api.adminExists } }
        : {
            data: api.session,
            error: api.ended ? { detail: api.ended } : null,
          },
  }),
}));

beforeEach(() => {
  fetchMock.mockReset();
  navigation.replace.mockReset();
  Object.assign(api, { adminExists: true, session: null, ended: null });
});

afterEach(cleanup);

function answer(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function signIn() {
  render(<SignInForm next="/screener" />);
  type("Username", "darshil929");
  type("Password", "lantern-orchard-basalt");
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

test("signing in sends the username and password, then opens the address that sent the person here", async () => {
  fetchMock.mockResolvedValue(answer({ username: "darshil929" }, 200));

  signIn();

  await waitFor(() =>
    expect(navigation.replace).toHaveBeenCalledWith("/screener"),
  );
  const [request] = fetchMock.mock.lastCall ?? [];
  expect(request?.url).toBe("http://localhost:3000/api/auth/sign-in");
  expect(await request?.json()).toEqual({
    username: "darshil929",
    password: "lantern-orchard-basalt",
  });
});

const PAUSED = "2026-10-17T19:50:00Z";

test.each([
  ["wrong_credentials", "The username or password is not right"],
  ["paused", "Sign-in for this username is paused until 18 Oct 2026, 01:20."],
  ["disabled", "This account is disabled. An administrator can enable it."],
  ["temporary_password_expired", "This temporary password has expired."],
])("a refusal %s reads as it is drawn", async (reason, words) => {
  const detail = { reason, paused_until: reason === "paused" ? PAUSED : null };
  fetchMock.mockResolvedValue(answer({ detail }, 401));

  signIn();

  expect(await screen.findByText(words, { exact: false })).toBeDefined();
  expect(navigation.replace).not.toHaveBeenCalled();
});

test.each([
  ["idle", "Signed out after 2 hours without activity."],
  ["limit", "Signed out at the 12-hour limit. Sign in again to continue."],
  ["signed_out_elsewhere", "Signed out from another session."],
])("a session that ended, %s, says why", async (reason, words) => {
  api.ended = { reason, ended_at: PAUSED, idle_minutes: 120, max_hours: 12 };

  render(await SignInPage({ searchParams: Promise.resolve({}) }));

  expect(screen.getByText(words)).toBeDefined();
  expect(screen.getByRole("heading", { name: "Disclaimer" })).toBeDefined();
});

test("after signing out, sign-in says so", async () => {
  api.ended = {
    reason: null,
    ended_at: null,
    idle_minutes: null,
    max_hours: null,
  };

  render(
    await SignInPage({
      searchParams: Promise.resolve({ ended: "signed_out" }),
    }),
  );

  expect(screen.getByText("Signed out.")).toBeDefined();
});

test("sign-in gives way to setup while no admin exists, and to the next page for someone signed in", async () => {
  api.adminExists = false;
  await expect(
    SignInPage({ searchParams: Promise.resolve({}) }),
  ).rejects.toThrow("redirected to /setup");

  api.adminExists = true;
  api.session = { username: "darshil929", must_change_password: false };
  await expect(
    SignInPage({ searchParams: Promise.resolve({ next: "/watchlist" }) }),
  ).rejects.toThrow("redirected to /watchlist");
});

test.each([
  ["/instrument/INE040A01034?venue=NSE", "/instrument/INE040A01034?venue=NSE"],
  ["https://elsewhere.example", "/"],
  ["//elsewhere.example", "/"],
  ["/\\elsewhere.example", "/"],
  [undefined, "/"],
])("the return address %s opens %s", (next, opened) => {
  expect(returnAddress(next)).toBe(opened);
});

test("a session holding a temporary password chooses a new one in place of the form", async () => {
  api.session = {
    display_name: "Darshil Thakkar",
    must_change_password: true,
  };

  render(await SignInPage({ searchParams: Promise.resolve({}) }));

  expect(
    screen.getByRole("heading", { name: "Choose a new password" }),
  ).toBeDefined();
  expect(
    screen.getByText("Darshil Thakkar signed in with a temporary password.", {
      exact: false,
    }),
  ).toBeDefined();
  expect(screen.queryByLabelText("Username")).toBeNull();
});

function chooseNewPassword(again = "harbour-lantern-quince") {
  render(<NewPasswordForm displayName="Darshil Thakkar" next="/screener" />);
  type("New password", "harbour-lantern-quince");
  type("New password again", again);
  fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));
}

test.each([204, 409])(
  "a new password answered %s opens the address that sent the person here",
  async (status) => {
    fetchMock.mockResolvedValue(
      status === 204
        ? new Response(null, { status })
        : answer({ detail: "no_change_due" }, status),
    );

    chooseNewPassword();

    await waitFor(() =>
      expect(navigation.replace).toHaveBeenCalledWith("/screener"),
    );
    const [request] = fetchMock.mock.lastCall ?? [];
    expect(request?.url).toBe("http://localhost:3000/api/auth/password");
    expect(await request?.json()).toEqual({
      password: "harbour-lantern-quince",
    });
  },
);

test("two new passwords that differ are refused before anything is sent", () => {
  chooseNewPassword("harbour-lantern-quinces");

  expect(screen.getByText("The two passwords differ")).toBeDefined();
  expect(fetchMock).not.toHaveBeenCalled();
});

test.each([
  [
    422,
    "contains_a_name",
    "The password may not contain the username, the display name or Bitemporal",
  ],
  [503, "unavailable", "The password could not be saved. Try again."],
])("a new password refused %s %s says why", async (status, detail, words) => {
  fetchMock.mockResolvedValue(answer({ detail }, status));

  chooseNewPassword();

  expect(await screen.findByText(words)).toBeDefined();
  expect(navigation.replace).not.toHaveBeenCalled();
});
