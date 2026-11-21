import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { UsersPeopleSection } from "@/app/(app)/admin/users/UsersPeopleSection";

const fetchMock = vi.hoisted(() => {
  vi.stubGlobal(
    "Request",
    class extends Request {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(
          typeof input === "string"
            ? new URL(input, window.location.href)
            : input,
          init,
        );
      }
    },
  );
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  vi.stubGlobal("fetch", mock);
  return mock;
});

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
const ADMIN = {
  id: 1,
  username: "darshil929",
  display_name: "Darshil",
  role: "admin" as const,
  disabled_at: null,
  must_change_password: false,
  created_at: "2026-10-02T12:30:00Z",
  last_signed_in: "2026-10-11T18:08:00Z",
};

beforeEach(() => (fetchMock.mockReset(), refresh.mockReset()));
afterEach(cleanup);

function submitAdd(name: string, username: string) {
  render(<UsersPeopleSection people={[ADMIN]} currentUserId={1} />);
  fireEvent.click(screen.getByRole("button", { name: "Add person" }));
  fireEvent.change(screen.getByLabelText("Display name"), {
    target: { value: name },
  });
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: username },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add person" }));
}

test("empty or short fields show inline errors without sending a request", () => {
  submitAdd("", "ab");
  expect(screen.getByText("Enter a display name")).toBeTruthy();
  expect(screen.getByText("Enter 3 to 64 characters")).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();
});

test("adding a person posts POST /admin/users, shows and copies the temporary password, and refreshes", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
  const added = { ...ADMIN, id: 2, username: "ananya", display_name: "Ananya" };
  fetchMock.mockResolvedValueOnce(
    Response.json(
      { person: added, temporary_password: "amber-cedar-river-seven" },
      { status: 201 },
    ),
  );
  submitAdd("Ananya", "ananya");

  expect(await screen.findByText("Ananya added")).toBeTruthy();
  expect(screen.getByLabelText("Temporary password")).toHaveProperty(
    "value",
    "amber-cedar-river-seven",
  );
  expect(screen.getByText("Expires in 24 hours.")).toBeTruthy();
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  const req = fetchMock.mock.lastCall?.[0];
  expect(req?.method).toBe("POST");
  expect(await req?.json()).toEqual({
    display_name: "Ananya",
    username: "ananya",
    role: "member",
  });
  fireEvent.click(screen.getByRole("button", { name: "Copy" }));
  expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
  expect(writeText).toHaveBeenCalledWith("amber-cedar-river-seven");
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  await waitFor(() => expect(screen.queryByText("Ananya added")).toBeNull());
});

test("a taken username shows an inline error on the username field", async () => {
  fetchMock.mockResolvedValueOnce(
    Response.json({ detail: "username_taken" }, { status: 409 }),
  );
  submitAdd("Ananya", "ananya");
  expect(
    await screen.findByText("This username is already taken"),
  ).toBeTruthy();
});
