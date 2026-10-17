// @vitest-environment node
import { beforeEach, expect, test, vi } from "vitest";

// Next's server modules read the AsyncLocalStorage its own server places on the global object.
await vi.hoisted(async () => {
  const { AsyncLocalStorage } = await import("node:async_hooks");
  Object.assign(globalThis, { AsyncLocalStorage });
});

const api = vi.hoisted(() => ({ status: 200, body: {} as unknown }));

vi.mock("@/lib/server-api-client", () => ({
  serverApiClient: async () => ({
    GET: async () => ({
      data: api.status === 200 ? api.body : undefined,
      error: api.status === 200 ? undefined : api.body,
      response: new Response(null, { status: api.status }),
    }),
  }),
}));

vi.mock("next/headers", () => ({
  headers: async () =>
    new Headers({ "x-requested-address": "/screener?page=2" }),
}));

vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`redirected to ${to}`);
  },
}));

const { getRedirectUrl, unstable_doesMiddlewareMatch } =
  await import("next/experimental/testing/server");
const { NextRequest } = await import("next/server");
const { default: SignedInLayout } = await import("@/app/(app)/layout");
const { requireSession } = await import("@/lib/page-access");
const { config, proxy } = await import("@/proxy");

const PERSON = {
  id: 1,
  username: "darshil929",
  display_name: "Darshil Thakkar",
  role: "admin",
  must_change_password: false,
};

beforeEach(() => {
  Object.assign(api, { status: 200, body: PERSON });
});

function pageRequest(address: string, cookie?: string) {
  return new NextRequest(new URL(address, "http://localhost:3000"), {
    headers: cookie ? { cookie } : {},
  });
}

test.each([
  [
    "/instrument/INE040A01034?venue=NSE",
    "/sign-in?next=%2Finstrument%2FINE040A01034%3Fvenue%3DNSE",
  ],
  ["/", "/sign-in"],
])("a request for %s without a session is sent to sign in", (address, to) => {
  expect(getRedirectUrl(proxy(pageRequest(address)))).toBe(
    `http://localhost:3000${to}`,
  );
});

test.each(["__Host-bitemporal_session", "bitemporal_session"])(
  "a request carrying %s goes on, telling the page its address",
  (cookie) => {
    const response = proxy(pageRequest("/screener?page=2", `${cookie}=token`));

    expect(getRedirectUrl(response)).toBeNull();
    expect(
      response.headers.get("x-middleware-request-x-requested-address"),
    ).toBe("/screener?page=2");
  },
);

test("sign-in, setup, the API and static files are reached without a session", () => {
  const checked = (url: string) =>
    unstable_doesMiddlewareMatch({ config, url });

  for (const url of ["/", "/screener", "/instrument/INE040A01034"]) {
    expect(checked(url)).toBe(true);
  }
  for (const url of [
    "/sign-in?next=%2F",
    "/setup",
    "/api/session",
    "/_next/static/app.js",
    "/favicon.ico",
  ]) {
    expect(checked(url)).toBe(false);
  }
});

test.each([
  ["ended", 401, { detail: { reason: "idle" } }],
  [
    "holding a temporary password",
    200,
    { ...PERSON, must_change_password: true },
  ],
])(
  "a session %s gives way to sign-in, returning to the page after",
  async (_, status, body) => {
    Object.assign(api, { status, body });

    await expect(SignedInLayout({ children: null })).rejects.toThrow(
      "redirected to /sign-in?next=%2Fscreener%3Fpage%3D2",
    );
  },
);

test("a running session gives the page its person; an unanswered read fails the page", async () => {
  await expect(requireSession()).resolves.toEqual(PERSON);

  Object.assign(api, { status: 503, body: { detail: "unavailable" } });
  await expect(requireSession()).rejects.toThrow("status 503");
});
