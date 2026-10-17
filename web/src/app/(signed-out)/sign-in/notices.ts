import type { components } from "@/lib/api";
import { formatDateTime, formatDuration } from "@/lib/format";

type SessionEnded = components["schemas"]["SessionEnded"];
type SignInRefused = components["schemas"]["SignInRefused"];

export type Notice = Readonly<{
  text: string;
  tone: "flag" | "neutral";
  /** The glyph beside it, named so a notice read on the server reaches the form as data. */
  glyph: "clock" | "info" | "alert";
  /** The notice names a time, which reads in India time. */
  isTimed?: boolean;
}>;

const ended = (text: string, glyph: Notice["glyph"] = "info"): Notice => ({
  text,
  tone: "neutral",
  glyph,
});
const refused = (text: string): Notice => ({
  text,
  tone: "flag",
  glyph: "alert",
});

const DISABLED = refused(
  "This account is disabled. An administrator can enable it.",
);

// Why the previous session is not running, its limits as the administrator set them.
export function sessionNotice(session: SessionEnded): Notice | undefined {
  const { reason, idle_minutes: idle, max_hours: hours } = session;
  if (reason === "idle" && idle !== null) {
    return ended(
      `Signed out after ${formatDuration(idle)} without activity.`,
      "clock",
    );
  }
  if (reason === "limit" && hours !== null) {
    return ended(
      `Signed out at the ${hours}-hour limit. Sign in again to continue.`,
      "clock",
    );
  }
  if (reason === "signed_out_elsewhere") {
    return ended("Signed out from another session.");
  }
  if (reason === "signed_out") {
    return ended("Signed out.");
  }
  return reason === "disabled" ? DISABLED : undefined;
}

// Why a sign-in was refused, where a banner says it; a wrong username or password is a line of its
// own under the fields, the same for either.
export function refusalNotice(refusal: SignInRefused): Notice | undefined {
  if (refusal.reason === "paused") {
    const until = refusal.paused_until;
    const text = "Too many attempts. Sign-in for this username is paused";
    return {
      ...refused(
        until ? `${text} until ${formatDateTime(until)}.` : `${text}.`,
      ),
      isTimed: true,
    };
  }
  if (refusal.reason === "temporary_password_expired") {
    return refused(
      "This temporary password has expired. An administrator can set a new one.",
    );
  }
  return refusal.reason === "disabled" ? DISABLED : undefined;
}
