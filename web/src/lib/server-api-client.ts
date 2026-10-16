import createFetchClient, { type Client } from "openapi-fetch";
import { headers } from "next/headers";

import type { paths } from "@/lib/api";

const LOCAL_API_URL = "http://localhost:8000";

// A page fetches on the server, from the API's own address, with the cookies of the request it
// answers, so the API reads as the person signed in.
export async function serverApiClient(): Promise<Client<paths>> {
  const cookie = (await headers()).get("cookie");
  return createFetchClient<paths>({
    baseUrl: process.env.API_URL ?? LOCAL_API_URL,
    headers: cookie ? { cookie } : {},
  });
}
