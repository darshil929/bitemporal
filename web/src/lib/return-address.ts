// A page to return to after signing in: only an address on this site, so a crafted link cannot send
// someone elsewhere once they have signed in. A path beginning `//` or `/\` names another host.
export function returnAddress(next: string | undefined): string {
  if (
    !next?.startsWith("/") ||
    next.startsWith("//") ||
    next.startsWith("/\\")
  ) {
    return "/";
  }
  return next;
}

// The address a page request asked for, carried to the page in a request header: a server component
// is not told its own address.
export const REQUESTED_ADDRESS_HEADER = "x-requested-address";

// Sign-in, holding the page to return to once signed in.
export function signInAddress(next: string): string {
  return next === "/"
    ? "/sign-in"
    : `/sign-in?${new URLSearchParams({ next })}`;
}

// Sign-in once signed out, saying so.
export const SIGNED_OUT_ADDRESS = "/sign-in?ended=signed_out";
