/**
 * A screen's criteria as the screener's address writes them, `figure:comparison:value`, and as a
 * chip reads them: the figure's name, the comparison's sign and the threshold in the figure's own
 * unit. Scaling a threshold to percent or crore changes only how it reads.
 */

type Unit = "fraction" | "percent" | "crore" | "number" | "multiple" | "bps";

// The figures a screen compares, each with the unit its threshold reads in: returns,
// volatility and the distance from the high are fractions read as percent, delivery is already in
// percent, traded value is in rupees read in crore.
export const FIGURES = {
  return_1d: { label: "Return 1D", unit: "fraction" },
  return_1w: { label: "Return 1W", unit: "fraction" },
  return_1m: { label: "Return 1M", unit: "fraction" },
  return_3m: { label: "Return 3M", unit: "fraction" },
  return_6m: { label: "Return 6M", unit: "fraction" },
  return_1y: { label: "Return 1Y", unit: "fraction" },
  momentum_12_1: { label: "Momentum 12-1", unit: "fraction" },
  volatility_20d: { label: "Volatility 20D", unit: "fraction" },
  rsi_14: { label: "RSI 14", unit: "number" },
  adtv_20d: { label: "ADTV 20D", unit: "crore" },
  volume_ratio_20d: { label: "Volume vs 20D", unit: "multiple" },
  delivery_pct_1d: { label: "Delivery 1D", unit: "percent" },
  delivery_pct_20d: { label: "Delivery 20D", unit: "percent" },
  from_52w_high: { label: "From 52-week high", unit: "fraction" },
  venue_spread_bps: { label: "Venue spread", unit: "bps" },
} as const satisfies Record<string, Readonly<{ label: string; unit: Unit }>>;

export type FigureName = keyof typeof FIGURES;
export type Comparison = "gt" | "gte" | "lt" | "lte";

export const COMPARISONS: Readonly<
  Record<Comparison, Readonly<{ sign: string; words: string }>>
> = {
  gt: { sign: ">", words: "above" },
  gte: { sign: "≥", words: "at or above" },
  lt: { sign: "<", words: "below" },
  lte: { sign: "≤", words: "at or below" },
};

// The comparisons in the order a menu offers them.
export const COMPARISON_ORDER: readonly Comparison[] = [
  "gt",
  "gte",
  "lt",
  "lte",
];

export type Criterion = Readonly<{
  figure: FigureName;
  comparison: Comparison;
  value: number;
}>;

const MINUS = "−";

// Powers of ten from a stored value to the figure as read: 0.02 reads 2%, 250000000 reads 25 Cr.
const EXPONENTS: Readonly<Record<Unit, number>> = {
  fraction: 2,
  percent: 0,
  crore: -7,
  number: 0,
  multiple: 0,
  bps: 0,
};

const DECIMALS: Readonly<Record<Unit, readonly [number, number]>> = {
  fraction: [2, 2],
  percent: [1, 1],
  crore: [0, 2],
  number: [0, 2],
  multiple: [2, 2],
  bps: [0, 0],
};

const UNITS: Readonly<Record<Unit, string>> = {
  fraction: "%",
  percent: "%",
  crore: "Cr",
  number: "",
  multiple: "×",
  bps: "bps",
};

function isFigure(name: string): name is FigureName {
  return Object.hasOwn(FIGURES, name);
}

export function isComparison(name: string): name is Comparison {
  return Object.hasOwn(COMPARISONS, name);
}

// Twelve significant figures drop the residue scaling leaves in a binary fraction: 0.0213 reads 2.13.
function shifted(value: number, exponent: number): number {
  return Number((value * 10 ** exponent).toPrecision(12));
}

function figures(value: number, unit: Unit, grouped = true): string {
  const [fewest, most] = DECIMALS[unit];
  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: fewest,
    maximumFractionDigits: most,
    useGrouping: grouped,
  })
    .format(value)
    .replace("-", MINUS);
}

/** A criterion the address writes as `figure:comparison:value`, or nothing where it names none. */
export function readCriterion(part: string): Criterion | null {
  const pieces = part.split(":");
  if (pieces.length !== 3) {
    return null;
  }
  const [figure, comparison, written] = pieces;
  const value = Number(written);
  if (
    !isFigure(figure) ||
    !isComparison(comparison) ||
    written === "" ||
    !Number.isFinite(value)
  ) {
    return null;
  }
  return { figure, comparison, value };
}

export function writeCriterion({ figure, comparison, value }: Criterion) {
  return `${figure}:${comparison}:${value}`;
}

/** The threshold as a chip reads it: `₹25 Cr`, `0.00%`, `50.0%`, `70`. */
export function thresholdText({ figure, value }: Criterion): string {
  const unit = FIGURES[figure].unit;
  const number = figures(shifted(value, EXPONENTS[unit]), unit);
  if (unit === "crore") {
    return `₹${number} Cr`;
  }
  return unit === "bps" ? `${number} bps` : `${number}${UNITS[unit]}`;
}

/** The threshold as its field holds it, in the figure's unit and without grouping. */
export function typedThreshold({ figure, value }: Criterion): string {
  const unit = FIGURES[figure].unit;
  return figures(shifted(value, EXPONENTS[unit]), unit, false);
}

/** The unit a threshold is typed in, shown after its field. */
export function thresholdUnit(figure: FigureName): string {
  return UNITS[FIGURES[figure].unit];
}

/** The stored value of a threshold typed in the figure's unit, or nothing where it is no number. */
export function thresholdFromTyped(
  figure: FigureName,
  typed: string,
): number | null {
  const text = typed.replaceAll(",", "").replace(MINUS, "-").trim();
  const number = Number(text);
  if (text === "" || !Number.isFinite(number)) {
    return null;
  }
  return shifted(number, -EXPONENTS[FIGURES[figure].unit]);
}
