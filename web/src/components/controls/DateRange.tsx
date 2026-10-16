import { SegmentedControl } from "@/components/controls/SegmentedControl";
import type { paths } from "@/lib/api";

export type PriceRange = NonNullable<
  paths["/instruments/{isin}/prices"]["get"]["parameters"]["query"]["range"]
>;

// The ranges the price history offers, shortest first; six months unless the address names another.
export const PRICE_RANGES = [
  "1M",
  "3M",
  "6M",
  "1Y",
  "All",
] as const satisfies readonly PriceRange[];
export const DEFAULT_PRICE_RANGE: PriceRange = "6M";

type DateRangeProps = Readonly<{
  selected?: PriceRange;
  /** The address showing a range. */
  hrefFor: (range: PriceRange) => string;
}>;

export function DateRange({
  selected = DEFAULT_PRICE_RANGE,
  hrefFor,
}: DateRangeProps) {
  return (
    <SegmentedControl
      label="Range"
      segments={PRICE_RANGES.map((range) => ({
        label: range,
        href: hrefFor(range),
        isSelected: range === selected,
      }))}
    />
  );
}
