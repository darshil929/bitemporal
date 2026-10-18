/**
 * How a figure the API computed reads on screen: Indian grouping, a fixed number of decimals per
 * quantity, the minus sign U+2212 so signed columns align, and the currency symbol or unit kept
 * apart from the figure so it can render one step lighter. Nothing here derives a value; scaling
 * to lakh, crore or percent changes only how a value reads.
 */

export interface Formatted {
  /** The figure with its sign, and a percent sign where the quantity is a percentage. */
  text: string;
  /** A currency symbol shown before the figure. */
  prefix?: string;
  /** A unit shown after the figure, set slightly apart from it. */
  unit?: string;
}

export type Direction = "up" | "down" | "flat";

const RUPEE = "₹";
const MINUS = "−";
const LAKH = 100_000;
const CRORE = 10_000_000;
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];
const INDIA = "Asia/Kolkata";

const grouped = new Map<string, Intl.NumberFormat>();

function digits(value: number, fewest: number, most: number = fewest): string {
  const key = `${fewest}:${most}`;
  let format = grouped.get(key);
  if (!format) {
    format = new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: fewest,
      maximumFractionDigits: most,
      roundingMode: "halfExpand",
    });
    grouped.set(key, format);
  }
  return format.format(value).replace("-", MINUS);
}

function signed(value: number, places: number): string {
  const text = digits(Math.abs(value), places);
  if (Number(text.replaceAll(",", "")) === 0) {
    return text;
  }
  return (value > 0 ? "+" : MINUS) + text;
}

/** Lakh from 1,00,000 and crore from 1,00,00,000, with two decimals; below a lakh in full. */
function compact(value: number): Formatted {
  if (Math.abs(value) >= CRORE) {
    return { text: digits(value / CRORE, 2), unit: "Cr" };
  }
  if (Math.abs(value) >= LAKH) {
    return { text: digits(value / LAKH, 2), unit: "L" };
  }
  return { text: digits(value, 0) };
}

/** A price in rupees: `₹1,234.56`. */
export function formatPrice(rupees: number): Formatted {
  return { prefix: RUPEE, text: digits(rupees, 2) };
}

/** A value in rupees, such as turnover: `₹3.20 L`, `₹12.45 Cr`. */
export function formatLargeValue(rupees: number): Formatted {
  return { prefix: RUPEE, ...compact(rupees) };
}

/** A count of shares: `84,231`, `1.42 Cr`. */
export function formatVolume(shares: number): Formatted {
  return compact(shares);
}

/** A price on a chart's axis, whole where the tick is: `1,000`, `987.50`. */
export function formatPriceTick(rupees: number): string {
  return digits(rupees, Number.isInteger(rupees) ? 0 : 2);
}

/** A count of shares on a chart's axis, to as few decimals as the tick needs: `5 Cr`, `2.5 L`. */
export function formatVolumeTick(shares: number): string {
  if (shares >= CRORE) {
    return `${digits(shares / CRORE, 0, 2)} Cr`;
  }
  return shares >= LAKH
    ? `${digits(shares / LAKH, 0, 2)} L`
    : digits(shares, 0);
}

/** An adjustment factor, to as many as four places: `0.5`, `0.0333`. */
export function formatFactor(factor: number): string {
  return digits(factor, 0, 4);
}

/** A change in price: `+15.30`, `−2.05`. */
export function formatChange(change: number): Formatted {
  return { text: signed(change, 2) };
}

/** A return given as a fraction, 0.0124 reading `+1.24%`. */
export function formatReturn(fraction: number): Formatted {
  return { text: `${signed(fraction * 100, 2)}%` };
}

/** A gap in basis points: `24 bps`. */
export function formatBps(bps: number): Formatted {
  return { text: digits(bps, 0), unit: "bps" };
}

/** A delivery share already in percent: `43.2%`. */
export function formatDeliveryShare(percent: number): Formatted {
  return { text: `${digits(percent, 1)}%` };
}

/** A multiple, such as a volume ratio: `1.56×`. */
export function formatMultiple(multiple: number): Formatted {
  return { text: digits(multiple, 2), unit: "×" };
}

/** A dividend in rupees a share, to the paisa or to the fraction of one the venue states. */
export function formatDividend(rupees: number): Formatted {
  return { prefix: RUPEE, text: digits(rupees, 2, 4) };
}

/** A calendar day from the API's `YYYY-MM-DD`: `16 Sep 2026`. */
export function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

/** A calendar day without its year, beside a figure whose year is evident: `16 Sep`. */
export function formatShortDate(isoDate: string): string {
  const [, month, day] = isoDate.split("-").map(Number);
  return `${day} ${MONTHS[month - 1]}`;
}

/** A month on a chart's time axis, numbered from 1: `Sep`. */
export function formatMonth(month: number): string {
  return MONTHS[month - 1];
}

const indiaParts = new Intl.DateTimeFormat("en-GB", {
  timeZone: INDIA,
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** A moment in India time: `16 Sep 2026, 14:05`. */
export function formatDateTime(isoTimestamp: string): string {
  const parts = Object.fromEntries(
    indiaParts
      .formatToParts(new Date(isoTimestamp))
      .map((part) => [part.type, part.value]),
  );
  const day = `${parts.year}-${parts.month}-${parts.day}`;
  return `${formatDate(day)}, ${parts.hour}:${parts.minute}`;
}

const MINUTES_IN_HOUR = 60;

/** A length of time given in minutes, in whole hours where it divides evenly: `2 hours`, `90 minutes`. */
export function formatDuration(minutes: number): string {
  const [count, unit] =
    minutes % MINUTES_IN_HOUR === 0
      ? [minutes / MINUTES_IN_HOUR, "hour"]
      : [minutes, "minute"];
  return `${count} ${unit}${count === 1 ? "" : "s"}`;
}

/** Which way a signed figure moved, read from the sign it shows, so a change that rounds to
 * nothing takes no colour. */
export function direction({ text }: Formatted): Direction {
  if (text.startsWith("+")) {
    return "up";
  }
  return text.startsWith(MINUS) ? "down" : "flat";
}

/** The figure as plain text, for a tooltip or an accessible label. */
export function asText({ prefix = "", text, unit }: Formatted): string {
  return `${prefix}${text}${unit ? (unit === "×" ? unit : ` ${unit}`) : ""}`;
}
