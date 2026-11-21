import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import UsersPage from "@/app/(app)/admin/users/page";
import {
  auditDetail,
  type AuditEntry,
  type ManagedPerson,
} from "@/lib/user-management";

const session = vi.hoisted(() => ({
  id: 1,
  role: "admin" as "admin" | "member",
  display_name: "Darshil",
}));

vi.mock("@/lib/page-access", () => ({ requireSession: async () => session }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const BASE_PERSON: ManagedPerson = {
  id: 1,
  username: "darshil929",
  display_name: "Darshil",
  role: "admin",
  disabled_at: null,
  must_change_password: false,
  created_at: "2026-10-02T12:30:00Z",
  last_signed_in: "2026-10-11T18:08:00Z",
};

const PEOPLE: ManagedPerson[] = [
  {
    ...BASE_PERSON,
    id: 3,
    username: "ananya",
    display_name: "Ananya",
    role: "member",
    must_change_password: true,
    last_signed_in: null,
  },
  {
    ...BASE_PERSON,
    id: 2,
    username: "rohan",
    display_name: "Rohan",
    role: "member",
    disabled_at: "2026-10-09T12:15:00Z",
  },
  BASE_PERSON,
];

const AUDIT: AuditEntry[] = [
  {
    occurred_at: "2026-10-11T18:11:00Z",
    actor_id: 1,
    actor_name: "Darshil",
    action: "sync_started",
    subject_id: null,
    subject_name: null,
    detail: { request_id: 4, first_day: "2026-10-05", last_day: "2026-10-11" },
  },
];

const SETTINGS = {
  session_idle_minutes: 120,
  session_max_hours: 12,
  updated_at: "2026-10-02T12:30:00Z",
};

vi.mock("@/lib/server-api-client", () => ({
  serverApiClient: async () => ({
    GET: async (path: string) => ({
      data:
        path === "/admin/users"
          ? PEOPLE
          : path === "/admin/settings"
            ? SETTINGS
            : AUDIT,
    }),
  }),
}));

afterEach(cleanup);

test("an admin reads the people table with active, disabled, and pending-password states", async () => {
  session.role = "admin";
  session.display_name = "Darshil";
  render(await UsersPage());

  expect(screen.getByRole("heading", { name: "Users" })).toBeTruthy();
  const table = screen.getByRole("table", {
    name: "People with accounts on this installation",
  });
  for (const label of [
    "This account",
    "Must change password",
    "Disabled",
    "Active",
    "Never",
  ]) {
    expect(within(table).getByText(label)).toBeTruthy();
  }
  expect(within(table).getAllByText("2 Oct 2026")).toHaveLength(3);
  expect(
    screen.getByText("3 people. Newest first. Times in India time"),
  ).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Session limits" })).toBeTruthy();
  const auditTable = screen.getByRole("table", {
    name: "Recent admin actions",
  });
  expect(within(auditTable).getByText("5 to 11 Oct 2026")).toBeTruthy();
});

test("audit detail formats limit changes and role changes", () => {
  const base = AUDIT[0];
  const limitsDetail = {
    idle_minutes: { from: 120, to: 90 },
    max_hours: { from: 12, to: 8 },
  };
  expect(
    auditDetail({
      ...base,
      action: "session_limits_changed",
      detail: limitsDetail,
    }),
  ).toBe("Idle 120 to 90 min, Max 12 to 8 h");
  expect(
    auditDetail({
      ...base,
      action: "role_changed",
      subject_name: "Ananya",
      detail: { from: "member", to: "admin" },
    }),
  ).toBe("Ananya, member to admin");
});

test("a member sees a not-permitted message with a link back to the dashboard", async () => {
  session.role = "member";
  session.display_name = "Meera";
  render(await UsersPage());

  expect(screen.getByText("Only an admin manages people")).toBeTruthy();
  expect(
    screen.getByText(
      "This page lists every account and changes them. Meera is a member.",
    ),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Back to the dashboard" })
      .getAttribute("href"),
  ).toBe("/");
});
