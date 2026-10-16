import { QueryClient } from "@tanstack/react-query";

// Figures are published a few times a day at most, so a read stays current for minutes.
export const STALE_AFTER_MS = 5 * 60 * 1000;

// A sync's rebuild leaves market reads absent for a moment; the API then answers 503 with a
// reason and asks for a retry after 5 seconds. Every other refusal stands on a second asking.
export const MARKET_DATA_RETRY_DELAY_MS = 5_000;
const MARKET_DATA_RETRIES = 2;
const MARKET_DATA_UPDATING = "market_data_updating";

function isMarketDataUpdating(error: unknown): boolean {
  if (typeof error !== "object" || error === null || !("detail" in error)) {
    return false;
  }
  const { detail } = error;
  return (
    typeof detail === "object" &&
    detail !== null &&
    "reason" in detail &&
    detail.reason === MARKET_DATA_UPDATING
  );
}

export function retriesMarketData(failures: number, error: unknown): boolean {
  return failures < MARKET_DATA_RETRIES && isMarketDataUpdating(error);
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: STALE_AFTER_MS,
        retry: retriesMarketData,
        retryDelay: MARKET_DATA_RETRY_DELAY_MS,
      },
    },
  });
}
