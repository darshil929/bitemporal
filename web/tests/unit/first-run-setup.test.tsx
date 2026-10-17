import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { FirstAdminForm } from "@/app/(signed-out)/setup/FirstAdminForm";
import SetupPage from "@/app/(signed-out)/setup/page";

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
  refresh: vi.fn(),
  redirect: vi.fn((to: string) => {
    throw new Error(`redirected to ${to}`);
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: navigation.replace,
    refresh: navigation.refresh,
  }),
  redirect: navigation.redirect,
}));

const setup = vi.hoisted(() => ({ adminExists: false }));

vi.mock("@/lib/server-api-client", () => ({
  serverApiClient: async () => ({
    GET: async () => ({ data: { admin_exists: setup.adminExists } }),
  }),
}));

const PASSWORD = "lantern-orchard-basalt";

beforeEach(() => {
  fetchMock.mockReset();
  navigation.replace.mockReset();
});

afterEach(cleanup);

function answer(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function isInvalid(label: string): boolean {
  return screen.getByLabelText(label).getAttribute("aria-invalid") === "true";
}

function fill(again = PASSWORD) {
  render(<FirstAdminForm />);
  const typed: Record<string, string> = {
    "Display name": "Meera Rao",
    Username: "meera",
    Password: PASSWORD,
    "Password again": again,
  };
  for (const [label, value] of Object.entries(typed)) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(
    screen.getByRole("button", { name: "Create admin and continue" }),
  );
}

test("the first admin is created with what was typed, and the application opens", async () => {
  fetchMock.mockResolvedValue(answer({ username: "meera" }, 201));

  fill();

  await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/"));
  const [request] = fetchMock.mock.lastCall ?? [];
  expect(request?.method).toBe("POST");
  expect(request?.url).toBe("http://localhost:3000/api/setup/admin");
  expect(await request?.json()).toEqual({
    display_name: "Meera Rao",
    username: "meera",
    password: PASSWORD,
  });
});

test("two passwords that differ say so, and nothing is sent", () => {
  fill(`${PASSWORD}-again`);

  expect(isInvalid("Password again")).toBe(true);
  expect(screen.getByText("The two passwords differ")).toBeDefined();
  expect(fetchMock).not.toHaveBeenCalled();
});

test.each([
  ["too_short", "At least 15 characters"],
  [
    "contains_a_name",
    "The password may not contain the username, the display name or Bitemporal",
  ],
])("the rule's refusal %s reads under the password", async (reason, words) => {
  fetchMock.mockResolvedValue(answer({ detail: reason }, 422));

  fill();

  await waitFor(() => expect(isInvalid("Password")).toBe(true));
  expect(screen.getAllByText(words).at(-1)?.classList).toContain("text-flag");
  expect(navigation.replace).not.toHaveBeenCalled();
});

test("setup offers the first admin while none exists, and opens the application once one does", async () => {
  setup.adminExists = false;
  render(await SetupPage());
  expect(
    screen.getByRole("heading", { name: "Create the first admin" }),
  ).toBeDefined();
  expect(screen.getByRole("heading", { name: "Disclaimer" })).toBeDefined();
  expect(screen.getByText("Setting up")).toBeDefined();

  setup.adminExists = true;
  await expect(SetupPage()).rejects.toThrow("redirected to /");
});
