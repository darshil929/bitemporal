import type { components } from "@/lib/api";
import { formatDayRange } from "@/lib/format";

export type ManagedPerson = components["schemas"]["PersonResponse"];
export type IssuedPassword = components["schemas"]["IssuedPasswordResponse"];
export type PersonRole = ManagedPerson["role"];
export type SessionLimits = components["schemas"]["SessionLimitsResponse"];
export type AuditEntry = components["schemas"]["AuditEntryResponse"];

export const ROLE_LABELS: Record<ManagedPerson["role"], string> = {
  admin: "Admin",
  member: "Member",
};

const ACTION_LABELS: Record<AuditEntry["action"], string> = {
  first_admin_created: "Created the first admin",
  person_added: "Added a person",
  role_changed: "Changed role",
  account_disabled: "Disabled an account",
  account_enabled: "Enabled an account",
  password_reset: "Reset password",
  session_limits_changed: "Changed session limits",
  sync_started: "Started a sync",
  bootstrap_started: "Started the history load",
  run_cancelled: "Cancelled a run",
};

export const auditActionLabel = (a: AuditEntry["action"]): string =>
  ACTION_LABELS[a];

const str = (v: unknown): string | null => (typeof v === "string" ? v : null);

const limitPart = (v: unknown, label: string, unit: string): string | null => {
  if (!v || typeof v !== "object") return null;
  const { from, to } = v as { from?: unknown; to?: unknown };
  return typeof from === "number" && typeof to === "number"
    ? `${label} ${from} to ${to} ${unit}`
    : null;
};

const join = (parts: readonly (string | null | undefined)[]): string =>
  parts.filter(Boolean).join(", ");

/** Human-readable detail for each recorded admin action. */
export function auditDetail({
  action,
  subject_name: s,
  detail: d,
}: AuditEntry): string {
  if (action === "first_admin_created") return "First-run setup";
  if (action === "person_added") return join([s, str(d.role)]);
  if (action === "role_changed") {
    const [from, to] = [str(d.from), str(d.to)];
    return join([s, from && to ? `${from} to ${to}` : null]);
  }
  if (action === "session_limits_changed")
    return join([
      limitPart(d.idle_minutes, "Idle", "min"),
      limitPart(d.max_hours, "Max", "h"),
    ]);
  if (action === "sync_started" || action === "bootstrap_started") {
    const [first, last] = [str(d.first_day), str(d.last_day)];
    return first && last ? formatDayRange(first, last) : "";
  }
  if (action === "run_cancelled")
    return typeof d.request_id === "number" ? `Request #${d.request_id}` : "";
  return s ?? "";
}

const parseWhole = (text: string, min: number, max: number): number | null => {
  const trimmed = text.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const n = Number(trimmed);
  return n >= min && n <= max ? n : null;
};

export function validateSessionLimits(idleText: string, maxText: string) {
  const idle = parseWhole(idleText, 5, 1440);
  const max = parseWhole(maxText, 1, 72);
  return {
    idleError:
      idle === null ? "Enter a whole number from 5 to 1440" : undefined,
    maxError: max === null ? "Enter a whole number from 1 to 72" : undefined,
    parsed: idle !== null && max !== null ? { idle, max } : null,
  };
}

export function validateNewPerson(nameText: string, userText: string) {
  const display_name = nameText.trim();
  const username = userText.trim();
  const displayNameError = !display_name
    ? "Enter a display name"
    : display_name.length > 80
      ? "Use 80 characters or fewer"
      : undefined;
  const usernameError =
    username.length < 3 || username.length > 64
      ? "Enter 3 to 64 characters"
      : undefined;
  return {
    displayNameError,
    usernameError,
    parsed:
      !displayNameError && !usernameError ? { display_name, username } : null,
  };
}

export type AccountActionKind =
  "make_admin" | "make_member" | "disable" | "enable" | "reset";

const LAST_ADMIN = "The last admin cannot be demoted or disabled";
const OWN_ACCOUNT = "An admin never disables their own account";

/** Disabled reasons for a row's role-change and disable items. */
export function accountProtection(
  person: ManagedPerson,
  people: readonly ManagedPerson[],
  currentUserId: number,
) {
  const other = people.some(
    (o) => o.id !== person.id && o.role === "admin" && o.disabled_at === null,
  );
  const last = person.role === "admin" && person.disabled_at === null && !other;
  const self = person.id === currentUserId;
  const both = [last ? LAST_ADMIN : null, self ? OWN_ACCOUNT : null]
    .filter(Boolean)
    .join(". ");
  return {
    demoteReason: last ? LAST_ADMIN : undefined,
    disableReason: both || undefined,
  };
}

/** Confirmation dialog copy for an account action. */
export function accountActionCopy(kind: AccountActionKind, name: string) {
  const rows: Record<
    AccountActionKind,
    readonly [string, string, readonly string[], string, string]
  > = {
    make_admin: [
      `Make ${name} an admin`,
      "An admin starts syncs and manages people.",
      [
        `${name} can start a sync and the history load`,
        `${name} can add, disable and reset people`,
        "Recorded in the admin actions",
      ],
      "Make admin",
      "Saving",
    ],
    make_member: [
      `Make ${name} a member`,
      "A member reads data and keeps their own watchlists, views and alerts.",
      [
        `${name} can no longer start syncs or manage people`,
        "Recorded in the admin actions",
      ],
      "Make member",
      "Saving",
    ],
    disable: [
      `Disable ${name}`,
      `${name} is signed out at once.`,
      [
        `Every session of ${name} ends now`,
        "Signing in is refused until an admin enables the account",
        "Watchlists, views and alerts are kept",
      ],
      "Disable account",
      "Disabling",
    ],
    enable: [
      `Enable ${name}`,
      `${name} can sign in again.`,
      [
        `${name} can sign in with their current password`,
        "Recorded in the admin actions",
      ],
      "Enable account",
      "Enabling",
    ],
    reset: [
      `Reset the password of ${name}`,
      "A temporary password replaces the current one.",
      [
        `Every session of ${name} ends now`,
        "The temporary password is shown once, and expires after 24 hours",
        `${name} chooses a new password at the next sign-in`,
      ],
      "Reset password",
      "Resetting",
    ],
  };
  const [title, description, changes, confirmLabel, busyLabel] = rows[kind];
  return { title, description, changes, confirmLabel, busyLabel };
}

const REFUSALS: Record<string, string> = {
  last_admin: `${LAST_ADMIN}.`,
  own_account: `${OWN_ACCOUNT}.`,
  person_not_found: "This account no longer exists. Reload the page.",
};

export const accountRefusalMessage = (detail: unknown): string =>
  (typeof detail === "string" && REFUSALS[detail]) ||
  "The change could not be saved. Try again.";
