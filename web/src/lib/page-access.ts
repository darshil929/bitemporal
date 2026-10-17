import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import type { components } from "@/lib/api";
import {
  REQUESTED_ADDRESS_HEADER,
  returnAddress,
  signInAddress,
} from "@/lib/return-address";
import { serverApiClient } from "@/lib/server-api-client";

export type SignedInPerson = components["schemas"]["SessionResponse"];

// The person a page is shown to, read once per request however many server components ask. Without a
// running session, or while a temporary password stands, the page gives way to sign-in, which says
// why and returns to the page once signed in.
export const requireSession = cache(async (): Promise<SignedInPerson> => {
  const client = await serverApiClient();
  const { data, response } = await client.GET("/session");
  if (data && !data.must_change_password) {
    return data;
  }
  if (data || response.status === 401) {
    const requested = (await headers()).get(REQUESTED_ADDRESS_HEADER);
    redirect(signInAddress(returnAddress(requested ?? undefined)));
  }
  throw new Error(`The session read failed with status ${response.status}`);
});
