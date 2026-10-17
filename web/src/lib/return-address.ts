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
