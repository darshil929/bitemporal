import {
  type AreaData,
  AreaSeries,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  LineStyle,
  type Time,
  type WhitespaceData,
} from "lightweight-charts";

import type { components } from "@/lib/api";
import { formatPriceTick } from "@/lib/format";

import type { ChartColours } from "./chart-colours";

type PriceDay = components["schemas"]["PriceDayResponse"];

// The gap between the venues' closes beyond which a day may diverge; the API flags a divergent day,
// and the panel draws this line as a reference wherever its axis reaches it.
export const SPREAD_LIMIT_BPS = 500;
// The axis takes in the limit once the widest spread comes within this share of it, then leaves
// room above it; otherwise it scales to the spreads alone.
const LIMIT_IN_VIEW_FROM = 0.4;
const ROOM_ABOVE_LIMIT = 1.2;
const ROOM_ABOVE_SPREAD = 1.25;
// The area under the line, as a hex alpha: a tenth of the line's colour.
const FILL_ALPHA = "1a";

// How far up the spread axis reaches for the range's widest spread.
export function spreadAxisTop(widest: number): number {
  return widest >= SPREAD_LIMIT_BPS * LIMIT_IN_VIEW_FROM
    ? Math.max(SPREAD_LIMIT_BPS * ROOM_ABOVE_LIMIT, widest * ROOM_ABOVE_SPREAD)
    : widest * ROOM_ABOVE_SPREAD;
}

function spreadPoint(
  day: PriceDay,
  colours: ChartColours,
): AreaData<Time> | WhitespaceData<Time> {
  const time = day.trade_date;
  if (day.venue_spread_bps === null) {
    return { time };
  }
  return day.is_diverging
    ? {
        time,
        value: day.venue_spread_bps,
        lineColor: colours.flag,
        topColor: colours.flagSurface,
        bottomColor: colours.flagSurface,
      }
    : { time, value: day.venue_spread_bps };
}

// The two venues' closes compared day by day in their own pane, divergent days in the flag colour.
export function addSpreadArea(
  chart: IChartApi,
  days: readonly PriceDay[],
  pane: number,
  headerShare: number,
): {
  paint: (colours: ChartColours) => void;
  series: ISeriesApi<"Area">;
} {
  const widest = Math.max(...days.map((day) => day.venue_spread_bps ?? 0));
  const top = spreadAxisTop(widest);
  const series = chart.addSeries(
    AreaSeries,
    {
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      priceFormat: { type: "custom", formatter: formatPriceTick },
      autoscaleInfoProvider: () => ({
        priceRange: { minValue: 0, maxValue: top },
      }),
    },
    pane,
  );
  series.priceScale().applyOptions({
    scaleMargins: { top: headerShare, bottom: 0 },
  });
  let limit: IPriceLine | undefined;
  return {
    series,
    paint(colours) {
      const fill = `${colours.textMuted}${FILL_ALPHA}`;
      series.applyOptions({
        lineColor: colours.textMuted,
        topColor: fill,
        bottomColor: fill,
      });
      series.setData(days.map((day) => spreadPoint(day, colours)));
      if (top < SPREAD_LIMIT_BPS) {
        return;
      }
      if (limit) {
        series.removePriceLine(limit);
      }
      limit = series.createPriceLine({
        price: SPREAD_LIMIT_BPS,
        color: colours.flag,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "Limit",
      });
    },
  };
}
