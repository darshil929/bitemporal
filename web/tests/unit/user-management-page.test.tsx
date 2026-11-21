import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import UsersPage from "@/app/(app)/admin/users/page";
import type { ManagedPerson } from "@/lib/user-management";

const session = vi.hoisted(() => ({
  id: 1,
  role: "admin" as "admin" | "member",
  display_name: "Darshil",
}));

vi.mock("@/lib/page-access", () => ({ requireSession: async () => session }));

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

vi.mock("@/lib/server-api-client", () => ({
  serverApiClient: async () => ({
    GET: async () => ({ data: PEOPLE }),
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
  expect(
    screen.getByText("3 people. Newest first. Times in India time"),
  ).toBeTruthy();
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
