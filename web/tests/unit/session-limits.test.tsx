import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { SessionLimitsCard } from "@/app/(app)/admin/users/SessionLimitsCard";

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
const LIMITS = {
  session_idle_minutes: 120,
  session_max_hours: 12,
  updated_at: "2026-10-02T12:30:00Z",
};

beforeEach(() => (fetchMock.mockReset(), refresh.mockReset()));
afterEach(cleanup);

test("out-of-range session limits show inline errors without sending a request", () => {
  render(<SessionLimitsCard limits={LIMITS} />);
  fireEvent.change(screen.getByLabelText("Idle limit"), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByText("Enter a whole number from 5 to 1440")).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();
});

test("saving valid session limits sends PATCH /admin/settings, shows Saved, and refreshes", async () => {
  const payload = { ...LIMITS, session_idle_minutes: 90, session_max_hours: 8 };
  fetchMock.mockResolvedValueOnce(Response.json(payload));
  render(<SessionLimitsCard limits={LIMITS} />);
  fireEvent.change(screen.getByLabelText("Idle limit"), {
    target: { value: "90" },
  });
  fireEvent.change(screen.getByLabelText("Maximum"), {
    target: { value: "8" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText("Saved")).toBeTruthy();
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  const req = fetchMock.mock.lastCall?.[0];
  expect([req?.method, req?.url]).toEqual([
    "PATCH",
    "http://localhost:3000/api/admin/settings",
  ]);
});

test("a failed session limits save shows an alert", async () => {
  fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
  render(<SessionLimitsCard limits={LIMITS} />);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect((await screen.findByRole("alert")).textContent).toContain(
    "The session limits could not be saved. Try again.",
  );
});
