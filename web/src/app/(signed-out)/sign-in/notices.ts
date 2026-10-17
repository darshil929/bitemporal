import type { components } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

type SignInRefused = components["schemas"]["SignInRefused"];

export type Notice = Readonly<{
  text: string;
  /** The notice names a time, which reads in India time. */
  isTimed?: boolean;
}>;

const PAUSED = "Too many attempts. Sign-in for this username is paused";

// Why a sign-in was refused, where a banner says it; a wrong username or password is a line of its
// own under the fields, the same for either.
export function refusalNotice(refusal: SignInRefused): Notice | undefined {
  switch (refusal.reason) {
    case "paused":
      return {
        text: refusal.paused_until
          ? `${PAUSED} until ${formatDateTime(refusal.paused_until)}.`
          : `${PAUSED}.`,
        isTimed: true,
      };
    case "disabled":
      return {
        text: "This account is disabled. An administrator can enable it.",
      };
    case "temporary_password_expired":
      return {
        text: "This temporary password has expired. An administrator can set a new one.",
      };
    default:
      return undefined;
  }
}
