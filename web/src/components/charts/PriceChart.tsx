"use client";

import {
  CandlestickSeries,
  type CandlestickSeriesPartialOptions,
  ColorType,
  createChart,
  CrosshairMode,
  type DeepPartial,
  type TimeChartOptions,
  LineStyle,
  type Time,
  TickMarkType,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { NullValue } from "@/components/values/NullValue";
import type { components } from "@/lib/api";
import {
  formatDate,
  formatMonth,
  formatPrice,
  formatPriceTick,
  formatVolumeTick,
} from "@/lib/format";

import {
  type ChartColours,
  chartColours,
  onThemeChange,
} from "./chart-colours";
import {
  type VolumeBar,
  type VolumeBarOptions,
  VolumeBars,
} from "./volume-bars";

type PriceDay = components["schemas"]["PriceDayResponse"];
type Venue = components["schemas"]["PriceHistoryResponse"]["venue"];

const PRICE_PANE_HEIGHT = 290;
const VOLUME_HEADER_HEIGHT = 28;
// Between the volume pane's header and its tallest bar.
const VOLUME_HEADER_GAP = 6;
const VOLUME_PANE_HEIGHT = VOLUME_HEADER_HEIGHT + 70;
const PANE_SEPARATOR_HEIGHT = 1;
const TIME_AXIS_HEIGHT = 28;
const AXIS_WIDTH = 64;
const AXIS_FONT_SIZE = 11;
// The highest and lowest prices sit this far inside the price pane.
const PRICE_MARGIN = 0.06;

// Months, and years where a range crosses one; the days between are left unlabelled. The axis
// names a day as the data did, here `YYYY-MM-DD`, or as a business day.
function timeTick(time: Time, type: TickMarkType): string {
  const [year, month] =
    typeof time === "object"
      ? [time.year, time.month]
      : String(time).split("-").map(Number);
  if (type === TickMarkType.Year) {
    return String(year);
  }
  return type === TickMarkType.Month ? formatMonth(month) : "";
}

function chartOptions(
  colours: ChartColours,
  fontFamily: string,
): DeepPartial<TimeChartOptions> {
  return {
    autoSize: true,
    handleScroll: false,
    handleScale: false,
    layout: {
      background: { type: ColorType.Solid, color: colours.surfaceRaised },
      textColor: colours.textSubtle,
      fontSize: AXIS_FONT_SIZE,
      fontFamily,
      attributionLogo: true,
      panes: { separatorColor: colours.border, enableResize: false },
    },
    grid: {
      vertLines: { visible: false },
      horzLines: { color: colours.border },
    },
    rightPriceScale: {
      borderVisible: false,
      minimumWidth: AXIS_WIDTH,
      entireTextOnly: true,
    },
    timeScale: {
      borderVisible: false,
      fixLeftEdge: true,
      fixRightEdge: true,
      tickMarkFormatter: timeTick,
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      horzLine: { visible: false, labelVisible: false },
      vertLine: {
        color: colours.textMuted,
        width: 1,
        style: LineStyle.Solid,
        labelVisible: false,
      },
    },
  };
}

function candleColours(colours: ChartColours): CandlestickSeriesPartialOptions {
  return {
    upColor: colours.up,
    downColor: colours.down,
    wickUpColor: colours.up,
    wickDownColor: colours.down,
  };
}

function volumeColours(colours: ChartColours): Partial<VolumeBarOptions> {
  return {
    deliveredColor: colours.textMuted,
    notDeliveredColor: colours.borderStrong,
    noFigureColor: colours.textSubtle,
  };
}

function volumeBar(day: PriceDay): VolumeBar {
  return {
    time: day.trade_date,
    volume: day.volume,
    delivered: day.delivery_quantity,
  };
}

function candle({ trade_date: time, open, high, low, close }: PriceDay) {
  return open === null || high === null || low === null || close === null
    ? { time }
    : { time, open, high, low, close };
}

type PriceChartProps = Readonly<{
  venue: Venue;
  /** The range's days at the venue, oldest first, as the price history read returns them. */
  days: readonly PriceDay[];
}>;

// One venue's candles, adjusted for every later split and bonus, with the shares traded under
// them; the row above reads the day under the crosshair, or the newest day.
export function PriceChart({ venue, days }: PriceChartProps) {
  const container = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState<number>();

  useEffect(() => {
    const element = container.current;
    if (!element) {
      return;
    }
    const colours = chartColours();
    const chart = createChart(
      element,
      chartOptions(colours, getComputedStyle(element).fontFamily),
    );
    const candles = chart.addSeries(CandlestickSeries, {
      ...candleColours(colours),
      borderVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
      priceFormat: { type: "custom", formatter: formatPriceTick },
    });
    candles.priceScale().applyOptions({
      scaleMargins: { top: PRICE_MARGIN, bottom: PRICE_MARGIN },
    });
    const volume = chart.addCustomSeries(
      new VolumeBars(),
      {
        ...volumeColours(colours),
        priceLineVisible: false,
        lastValueVisible: false,
        priceFormat: { type: "custom", formatter: formatVolumeTick },
      },
      1,
    );
    volume.priceScale().applyOptions({
      scaleMargins: {
        top: VOLUME_HEADER_HEIGHT / VOLUME_PANE_HEIGHT,
        bottom: 0,
      },
    });
    candles.setData(days.map(candle));
    volume.setData(days.map(volumeBar));
    const [pricePane, volumePane] = chart.panes();
    pricePane.setHeight(PRICE_PANE_HEIGHT);
    volumePane.setHeight(VOLUME_PANE_HEIGHT);
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove(({ logical }) =>
      setHovered(logical === undefined ? undefined : Math.round(logical)),
    );
    const stopWatching = onThemeChange(() => {
      const next = chartColours();
      chart.applyOptions(
        chartOptions(next, getComputedStyle(element).fontFamily),
      );
      candles.applyOptions(candleColours(next));
      volume.applyOptions(volumeColours(next));
    });
    return () => {
      stopWatching();
      chart.remove();
    };
  }, [days]);

  const shown =
    (hovered === undefined ? undefined : days[hovered]) ?? days.at(-1);

  return (
    <section className="flex flex-col gap-3 rounded-sm border border-border bg-surface-raised p-card">
      <div className="flex items-center gap-4">
        <h2 className="text-heading text-text">Price</h2>
        <span className="flex items-center gap-1.5 text-header font-normal text-text-muted">
          <svg aria-hidden="true" width="18" height="12" viewBox="0 0 18 12">
            <rect x="2" y="2" width="6" height="8" className="fill-up" />
            <rect x="10" y="3" width="6" height="7" className="fill-down" />
          </svg>
          {venue}
        </span>
      </div>
      {shown ? <DayReadout day={shown} /> : null}
      <div
        className="relative"
        style={{
          height:
            PRICE_PANE_HEIGHT +
            PANE_SEPARATOR_HEIGHT +
            VOLUME_PANE_HEIGHT +
            TIME_AXIS_HEIGHT,
        }}
      >
        <div ref={container} className="absolute inset-0" />
        <VolumeHeader top={PRICE_PANE_HEIGHT + PANE_SEPARATOR_HEIGHT} />
      </div>
    </section>
  );
}

function DayReadout({ day }: Readonly<{ day: PriceDay }>) {
  const prices = [
    ["O", day.open],
    ["H", day.high],
    ["L", day.low],
    ["C", day.close],
  ] as const;
  return (
    <p className="flex items-center gap-3 text-header">
      <span className="text-text">{formatDate(day.trade_date)}</span>
      {prices.map(([label, value]) => (
        <span key={label} className="flex gap-1 font-normal">
          <span className="text-text-subtle">{label}</span>
          <span className="text-text tabular-nums">
            {value === null ? (
              <NullValue reason="No price for this day" />
            ) : (
              formatPrice(value).text
            )}
          </span>
        </span>
      ))}
    </p>
  );
}

const VOLUME_KEYS = [
  ["fill-text-muted", "Delivered"],
  ["fill-border-strong", "Not delivered"],
  ["fill-text-subtle", "No delivery figure"],
] as const;

// Sits over the top of the volume pane, which the chart leaves empty for it.
function VolumeHeader({ top }: Readonly<{ top: number }>) {
  return (
    <div
      className="pointer-events-none absolute inset-x-0 z-10 flex items-center justify-between gap-4 bg-surface-raised"
      style={{ top, height: VOLUME_HEADER_HEIGHT - VOLUME_HEADER_GAP }}
    >
      <div className="flex items-center gap-4">
        <span className="text-cell font-medium text-text">Volume</span>
        <span className="flex items-center gap-3.5 text-header font-normal text-text-muted">
          {VOLUME_KEYS.map(([fill, label]) => (
            <span key={label} className="flex items-center gap-[5px]">
              <svg
                aria-hidden="true"
                width="10"
                height="12"
                viewBox="0 0 10 12"
              >
                <rect x="2" y="1" width="6" height="10" className={fill} />
              </svg>
              {label}
            </span>
          ))}
        </span>
      </div>
      <span className="text-caption text-text-subtle">
        Shares traded each day, adjusted for splits and bonuses
      </span>
    </div>
  );
}
