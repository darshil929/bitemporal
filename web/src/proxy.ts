import { type NextRequest, NextResponse } from "next/server";

import { REQUESTED_ADDRESS_HEADER, signInAddress } from "@/lib/return-address";

// The API names its session cookie with the `__Host-` prefix where it marks the cookie secure.
const SESSION_COOKIES = ["__Host-bitemporal_session", "bitemporal_session"];

// Every page but sign-in and setup is for someone signed in. A request carrying no session cookie is
// sent to sign in; one carrying a cookie goes on, and whether its session still runs is the API's to
// answer when the page reads it.
export function proxy(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;
  const requested = `${pathname}${search}`;
  if (!SESSION_COOKIES.some((name) => request.cookies.has(name))) {
    return NextResponse.redirect(
      new URL(signInAddress(requested), request.url),
    );
  }
  const headers = new Headers(request.headers);
  headers.set(REQUESTED_ADDRESS_HEADER, requested);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|sign-in|setup).*)"],
};
