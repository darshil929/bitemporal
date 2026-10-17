import createFetchClient from "openapi-fetch";
import createQueryHooks from "openapi-react-query";

import type { paths } from "@/lib/api";
import { signInAddress } from "@/lib/return-address";

// The browser calls the API through the web app's own address, which forwards /api to it, so the
// session cookie and the same-origin check on every change see a single origin.
export const API_PATH = "/api";

// The sign-in form's own refusal is a wrong username or password, which the form shows.
const SIGN_IN_PATH = "/auth/sign-in";

export const apiClient = createFetchClient<paths>({ baseUrl: API_PATH });

// A session that ends while a page is open has every later read refused. The page then gives way to
// sign-in, which says why and returns to the page once signed in; a whole page load leaves nothing
// read for the person in the browser.
apiClient.use({
  onResponse({ response, schemaPath }) {
    if (response.status === 401 && schemaPath !== SIGN_IN_PATH) {
      const { pathname, search } = window.location;
      window.location.assign(signInAddress(`${pathname}${search}`));
    }
  },
});

export const apiQueries = createQueryHooks(apiClient);
