import createFetchClient from "openapi-fetch";
import createQueryHooks from "openapi-react-query";

import type { paths } from "@/lib/api";

// The browser calls the API through the web app's own address, which forwards /api to it, so the
// session cookie and the same-origin check on every change see a single origin.
export const API_PATH = "/api";

export const apiClient = createFetchClient<paths>({ baseUrl: API_PATH });

export const apiQueries = createQueryHooks(apiClient);
