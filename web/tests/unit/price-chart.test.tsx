import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { type Time, TickMarkType } from "lightweight-charts";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { PriceChart } from "@/components/charts/PriceChart";
import { formatPriceTick } from "@/lib/format";

// The chart draws on a canvas the test DOM lacks, so the library is replaced by a record of what
// the chart is given.
const drawn = vi.hoisted(() => ({
  options: [] as Record<string, unknown>[],
  series: [] as { options: Record<string, unknown>[]; data: unknown[] }[],
  onCrosshair: (() => {}) as (event: { logical?: number }) => void,
}));

vi.mock("lightweight-charts", async (actual) => {
  const library = await actual<typeof import("lightweight-charts")>();
  const series = (options: Record<string, unknown>) => {
    const record = { options: [options], data: [] as unknown[] };
    drawn.series.push(record);
    return {
      setData: (data: unknown[]) => (record.data = data),
      applyOptions: (next: Record<string, unknown>) =>
        record.options.push(next),
      priceScale: () => ({ applyOptions: () => {} }),
    };
  };
  return {
    ...library,
    createChart: (_: HTMLElement, options: Record<string, unknown>) => {
      drawn.options.push(options);
      return {
        addSeries: (_definition: unknown, options: Record<string, unknown>) =>
          series(options),
        timeScale: () => ({ fitContent: () => {} }),
        subscribeCrosshairMove: (handler: typeof drawn.onCrosshair) =>
          (drawn.onCrosshair = handler),
        applyOptions: (next: Record<string, unknown>) =>
          drawn.options.push(next),
        remove: () => {},
      };
    },
  };
});

const OTHER_FIGURES = {
  close_as_traded: null,
  adjustment_factor: 1,
  volume: 15_123_456,
  delivery_quantity: null,
  other_venue_close: null,
  venue_spread_bps: null,
  is_diverging: null,
  sma_20: null,
  sma_50: null,
  sma_200: null,
  ema_20: null,
  ema_50: null,
  bollinger_20_upper: null,
  bollinger_20_lower: null,
};

const DAYS = [
  ["2025-09-30", 951.1, 958.4, 946.05, 954.2],
  ["2025-10-01", 955, 967.9, 953.25, 965.75],
].map(([trade_date, open, high, low, close]) => ({
  ...OTHER_FIGURES,
  trade_date: String(trade_date),
  open: Number(open),
  high: Number(high),
  low: Number(low),
  close: Number(close),
}));

beforeEach(() => {
  Object.assign(drawn, { options: [], series: [] });
  document.documentElement.style.setProperty("--color-up", "#007b55");
  document.documentElement.removeAttribute("data-theme");
});

afterEach(cleanup);

test("the chart draws the API's candles as given, months on its time axis, with the library's attribution", () => {
  render(<PriceChart venue="NSE" days={DAYS} />);

  const [candles] = drawn.series;
  expect(candles.data).toEqual([
    { time: "2025-09-30", open: 951.1, high: 958.4, low: 946.05, close: 954.2 },
    { time: "2025-10-01", open: 955, high: 967.9, low: 953.25, close: 965.75 },
  ]);
  const { timeScale } = drawn.options[0] as {
    timeScale: {
      tickMarkFormatter: (time: Time, type: TickMarkType) => string;
    };
  };
  expect(
    [
      ["2025-09-01", TickMarkType.Month],
      [{ year: 2026, month: 1, day: 1 }, TickMarkType.Year],
      ["2025-09-15", TickMarkType.DayOfMonth],
    ].map(([time, type]) =>
      timeScale.tickMarkFormatter(time as Time, type as TickMarkType),
    ),
  ).toEqual(["Sep", "2026", ""]);
  expect(drawn.options[0]).toMatchObject({
    handleScroll: false,
    handleScale: false,
    layout: { attributionLogo: true },
  });
  expect(screen.getByText("NSE")).toBeDefined();
});

test("candles take the theme's colours and follow a switch to dark", async () => {
  render(<PriceChart venue="NSE" days={DAYS} />);
  expect(drawn.series[0].options[0]).toMatchObject({ upColor: "#007b55" });

  document.documentElement.style.setProperty("--color-up", "#4fc994");
  document.documentElement.dataset.theme = "dark";

  await waitFor(() =>
    expect(drawn.series[0].options.at(-1)).toMatchObject({
      upColor: "#4fc994",
    }),
  );
});

test("the readout reads the newest day, then the day under the crosshair", () => {
  render(<PriceChart venue="NSE" days={DAYS} />);
  expect(screen.getByText("1 Oct 2025")).toBeDefined();
  expect(screen.getByText("965.75")).toBeDefined();

  act(() => drawn.onCrosshair({ logical: 0 }));

  expect(screen.getByText("30 Sep 2025")).toBeDefined();
  expect(screen.getByText("946.05")).toBeDefined();
});

test.each([
  [1000, "1,000"],
  [987.5, "987.50"],
])("the price axis reads %d as %s", (price, shown) => {
  expect(formatPriceTick(price)).toBe(shown);
});
