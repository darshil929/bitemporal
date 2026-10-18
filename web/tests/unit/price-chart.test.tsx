import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { type Time, TickMarkType } from "lightweight-charts";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { actionsAdjusting } from "@/components/charts/CrosshairCard";
import { PriceChart } from "@/components/charts/PriceChart";
import { spreadAxisTop } from "@/components/charts/spread-area";
import { barSegments } from "@/components/charts/volume-bars";
import type { components } from "@/lib/api";
import { formatPriceTick, formatVolumeTick } from "@/lib/format";

// The chart draws on a canvas the test DOM lacks, so the library is replaced by a record of what
// the chart is given.
const drawn = vi.hoisted(() => ({
  options: [] as Record<string, unknown>[],
  series: [] as { options: Record<string, unknown>[]; data: unknown[] }[],
  priceLines: [] as Record<string, unknown>[],
  onCrosshair: (() => {}) as (event: {
    logical?: number;
    point?: { x: number; y: number };
  }) => void,
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
      createPriceLine: (line: Record<string, unknown>) =>
        drawn.priceLines.push(line),
      removePriceLine: () => {},
    };
  };
  return {
    ...library,
    createChart: (_: HTMLElement, options: Record<string, unknown>) => {
      drawn.options.push(options);
      return {
        addSeries: (_definition: unknown, options: Record<string, unknown>) =>
          series(options),
        addCustomSeries: (_view: unknown, options: Record<string, unknown>) =>
          series(options),
        panes: () => drawn.series.map(() => ({ setStretchFactor: () => {} })),
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

function drawChart(
  days: components["schemas"]["PriceDayResponse"][] = DAYS,
  spreadMedian: number | null = null,
) {
  render(
    <PriceChart
      history={{
        isin: "INE040A01034",
        venue: "NSE",
        range: "6M",
        first_day: days[0].trade_date,
        last_day: days.at(-1)?.trade_date ?? null,
        days,
        venue_spread_median_bps: spreadMedian,
      }}
    />,
  );
}

beforeEach(() => {
  Object.assign(drawn, { options: [], series: [], priceLines: [] });
  document.documentElement.style.setProperty("--color-flag", "#9a6400");
  document.documentElement.style.setProperty("--color-flag-surface", "#fdf8ee");
  document.documentElement.style.setProperty("--color-up", "#007b55");
  document.documentElement.removeAttribute("data-theme");
});

afterEach(cleanup);

test("the chart draws the API's candles as given, months on its time axis, with the library's attribution", () => {
  drawChart();

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
  drawChart();
  expect(drawn.series[0].options[0]).toMatchObject({ upColor: "#007b55" });

  document.documentElement.style.setProperty("--color-up", "#4fc994");
  document.documentElement.dataset.theme = "dark";

  await waitFor(() =>
    expect(drawn.series[0].options.at(-1)).toMatchObject({
      upColor: "#4fc994",
    }),
  );
});

const POINT = { x: 120, y: 40 };

test("the readout reads the newest day, then the day under the crosshair", () => {
  drawChart();
  expect(screen.getByText("1 Oct 2025")).toBeDefined();
  expect(screen.getByText("965.75")).toBeDefined();

  act(() => drawn.onCrosshair({ logical: 0, point: POINT }));

  expect(screen.getAllByText("30 Sep 2025")).toHaveLength(2);
  expect(screen.getByText("946.05")).toBeDefined();
});

const BONUS = {
  ex_date: "2025-10-01",
  action_type: "bonus",
  qualifier: "",
  terms: "1 for 1",
  adjustment_factor: 0.5,
  dividend_amount: null,
  purpose: null,
  reported_by: "both",
  venues_differ: false,
  is_applied: true,
  source_id: null,
} as const;

test("the crosshair card adds the other venue's close and the spread, and the close as traded with the action adjusting it", () => {
  const [before] = DAYS;
  drawChart(
    [
      {
        ...before,
        adjustment_factor: 0.5,
        close_as_traded: 1908.4,
        other_venue_close: 954.35,
        venue_spread_bps: 1.5,
      },
    ],
    1.5,
  );

  act(() => drawn.onCrosshair({ logical: 0, point: POINT }));

  for (const words of ["BSE close, adjusted", "954.35", "1,908.40"]) {
    expect(screen.getByText(words)).toBeDefined();
  }
  expect(screen.getByText("Factor 0.5", { exact: false }).textContent).toBe(
    "Factor 0.5",
  );
});

test("the card names the actions after a day that its factor brings it through", () => {
  const [day] = DAYS;
  const dividend = {
    ...BONUS,
    action_type: "dividend" as const,
    adjustment_factor: null,
  };

  expect(actionsAdjusting(day, [BONUS, dividend])).toBe(
    "the 1 for 1 bonus with ex-date 1 Oct 2025",
  );
  expect(actionsAdjusting({ ...day, trade_date: "2025-10-01" }, [BONUS])).toBe(
    "",
  );
});

test("a single-listed instrument's card has no other venue", () => {
  drawChart(DAYS, null);

  act(() => drawn.onCrosshair({ logical: 0, point: POINT }));

  expect(screen.queryByText("BSE close, adjusted")).toBeNull();
});

test("the volume pane draws each day's shares traded and delivered as the API sends them", () => {
  const days = [DAYS[0], { ...DAYS[1], delivery_quantity: 6_512_300 }];
  drawChart(days);

  expect(drawn.series[1].data).toEqual([
    { time: "2025-09-30", volume: 15_123_456, delivered: null },
    { time: "2025-10-01", volume: 15_123_456, delivered: 6_512_300 },
  ]);
  expect(screen.getByText("No delivery figure")).toBeDefined();
});

test("both venues' closes compare in a spread pane under the range's median, divergent days in flag", () => {
  const [calm, divergent] = DAYS;
  drawChart(
    [
      { ...calm, venue_spread_bps: 2, is_diverging: false },
      { ...divergent, venue_spread_bps: 4, is_diverging: true },
    ],
    3,
  );

  expect(drawn.series[2].data).toEqual([
    { time: "2025-09-30", value: 2 },
    {
      time: "2025-10-01",
      value: 4,
      lineColor: "#9a6400",
      topColor: "#fdf8ee",
      bottomColor: "#fdf8ee",
    },
  ]);
  expect(
    screen.getByText(
      "Median 3 bps over the range. Limit 500 bps, beyond the axis",
    ),
  ).toBeDefined();
  expect(drawn.priceLines).toEqual([]);
});

test("a spread within reach of the limit brings the 500 bps line into view", () => {
  drawChart([{ ...DAYS[0], venue_spread_bps: 320, is_diverging: true }], 320);

  expect(drawn.priceLines).toMatchObject([{ price: 500, title: "Limit" }]);
  expect(screen.getByText("Median 320 bps over the range.")).toBeDefined();
});

test("a single-listed instrument has no spread pane", () => {
  drawChart(DAYS, null);

  expect(drawn.series).toHaveLength(2);
  expect(screen.queryByText("Venue spread")).toBeNull();
});

test.each([
  [150, 187.5],
  [250, 600],
  [700, 875],
])(
  "the spread axis reaches %d bps up to %d, taking in the 500 bps line once within reach",
  (widest, top) => {
    expect(spreadAxisTop(widest)).toBe(top);
  },
);

test("a bar holds the delivered shares at its base and the rest above a gap; without a figure it is whole", () => {
  const toY = (shares: number) => 100 - shares / 1000;

  expect(barSegments({ volume: 60_000, delivered: 20_000 }, toY)).toEqual([
    { top: 80, bottom: 100, tone: "delivered" },
    { top: 40, bottom: 78, tone: "notDelivered" },
  ]);
  expect(barSegments({ volume: 20_500, delivered: 20_000 }, toY)).toEqual([
    { top: 80, bottom: 100, tone: "delivered" },
  ]);
  expect(barSegments({ volume: 60_000, delivered: null }, toY)).toEqual([
    { top: 40, bottom: 100, tone: "noFigure" },
  ]);
});

test.each([
  [50_000_000, "5 Cr"],
  [250_000, "2.5 L"],
  [84_231, "84,231"],
])("the volume axis reads %d as %s", (shares, shown) => {
  expect(formatVolumeTick(shares)).toBe(shown);
});

test.each([
  [1000, "1,000"],
  [987.5, "987.50"],
])("the price axis reads %d as %s", (price, shown) => {
  expect(formatPriceTick(price)).toBe(shown);
});
