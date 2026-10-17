import {
  type CustomData,
  type CustomSeriesOptions,
  type CustomSeriesPricePlotValues,
  type CustomSeriesWhitespaceData,
  customSeriesDefaultOptions,
  type ICustomSeriesPaneRenderer,
  type ICustomSeriesPaneView,
  type PaneRendererCustomData,
  type PriceToCoordinateConverter,
  type Time,
} from "lightweight-charts";

export interface VolumeBar extends CustomData<Time> {
  /** Shares traded, adjusted for splits and bonuses. */
  volume: number;
  /** Shares delivered, adjusted alike; null where the venue published no delivery figure. */
  delivered: number | null;
}

export interface VolumeBarOptions extends CustomSeriesOptions {
  deliveredColor: string;
  notDeliveredColor: string;
  noFigureColor: string;
}

type Tone = "delivered" | "notDelivered" | "noFigure";

export type BarSegment = Readonly<{ top: number; bottom: number; tone: Tone }>;

// Delivered shares sit at the base of a bar and the rest above them, past a gap in the card's colour.
export const DELIVERY_GAP = 2;
const SMALLEST_SEGMENT = 1;

// The parts of one bar, top to bottom in pixels, from where the chart places a share count.
export function barSegments(
  bar: Pick<VolumeBar, "volume" | "delivered">,
  toY: (shares: number) => number,
): BarSegment[] {
  const base = toY(0);
  const top = toY(bar.volume);
  if (bar.delivered === null) {
    return [{ top, bottom: base, tone: "noFigure" }];
  }
  const deliveredTop = toY(bar.delivered);
  const segments: BarSegment[] = [
    { top: deliveredTop, bottom: base, tone: "delivered" },
  ];
  const restBottom = deliveredTop - DELIVERY_GAP;
  if (restBottom - top >= SMALLEST_SEGMENT) {
    segments.push({ top, bottom: restBottom, tone: "notDelivered" });
  }
  return segments;
}

// The chart's own width for a candle, which a bar takes so it sits under its candle: a fixed width
// over a band of narrow spacings, otherwise the spacing narrowed by up to a fifth as it widens.
const FIXED_WIDTH = { fromSpacing: 2.5, toSpacing: 4, width: 3 } as const;
const NARROWING_FROM_SPACING = 4;
const MOST_NARROWING = 0.2;

function candleWidth(barSpacing: number, pixelRatio: number): number {
  if (
    barSpacing >= FIXED_WIDTH.fromSpacing &&
    barSpacing <= FIXED_WIDTH.toSpacing
  ) {
    return Math.floor(FIXED_WIDTH.width * pixelRatio);
  }
  const widening =
    Math.max(NARROWING_FROM_SPACING, barSpacing) - NARROWING_FROM_SPACING;
  const narrowing = 1 - (MOST_NARROWING * Math.atan(widening)) / (Math.PI / 2);
  const width = Math.min(
    Math.floor(barSpacing * narrowing * pixelRatio),
    Math.floor(barSpacing * pixelRatio),
  );
  return Math.max(Math.floor(pixelRatio), width);
}

class VolumeBarsRenderer implements ICustomSeriesPaneRenderer {
  data: PaneRendererCustomData<Time, VolumeBar> | null = null;
  options: VolumeBarOptions | null = null;

  draw(
    target: Parameters<ICustomSeriesPaneRenderer["draw"]>[0],
    toY: PriceToCoordinateConverter,
  ): void {
    const { data, options } = this;
    if (!data?.visibleRange || !options) {
      return;
    }
    const { from, to } = data.visibleRange;
    const colours: Record<Tone, string> = {
      delivered: options.deliveredColor,
      notDelivered: options.notDeliveredColor,
      noFigure: options.noFigureColor,
    };
    target.useBitmapCoordinateSpace(
      ({ context, horizontalPixelRatio, verticalPixelRatio }) => {
        const width = candleWidth(data.barSpacing, horizontalPixelRatio);
        for (const bar of data.bars.slice(from, to)) {
          const left =
            Math.round(bar.x * horizontalPixelRatio) - Math.floor(width / 2);
          const at = (shares: number) => toY(shares) ?? 0;
          for (const { top, bottom, tone } of barSegments(
            bar.originalData,
            at,
          )) {
            const y = Math.round(top * verticalPixelRatio);
            context.fillStyle = colours[tone];
            context.fillRect(
              left,
              y,
              width,
              Math.round(bottom * verticalPixelRatio) - y,
            );
          }
        }
      },
    );
  }
}

// Shares traded each day, each bar split into the shares delivered and the rest.
export class VolumeBars implements ICustomSeriesPaneView<
  Time,
  VolumeBar,
  VolumeBarOptions
> {
  private readonly drawing = new VolumeBarsRenderer();

  renderer(): ICustomSeriesPaneRenderer {
    return this.drawing;
  }

  update(
    data: PaneRendererCustomData<Time, VolumeBar>,
    options: VolumeBarOptions,
  ): void {
    this.drawing.data = data;
    this.drawing.options = options;
  }

  priceValueBuilder(bar: VolumeBar): CustomSeriesPricePlotValues {
    return [0, bar.volume];
  }

  isWhitespace(
    bar: VolumeBar | CustomSeriesWhitespaceData<Time>,
  ): bar is CustomSeriesWhitespaceData<Time> {
    return !("volume" in bar);
  }

  defaultOptions(): VolumeBarOptions {
    return {
      ...customSeriesDefaultOptions,
      deliveredColor: "transparent",
      notDeliveredColor: "transparent",
      noFigureColor: "transparent",
    };
  }
}
