import type { Formatted } from "@/lib/format";

import { cn } from "cn";

type FigureProps = Readonly<{
  formatted: Formatted;
  /** The symbol and unit one step lighter than the figure; inheriting its colour where false. */
  isUnitLighter?: boolean;
}>;

// A figure with its currency symbol before it and its unit after it; a multiplication sign sits
// against the figure, a word unit a little apart.
export function Figure({ formatted, isUnitLighter = true }: FigureProps) {
  const lighter = isUnitLighter ? "text-text-subtle" : undefined;
  const { prefix, text, unit } = formatted;
  return (
    <>
      {prefix ? <span className={lighter}>{prefix}</span> : null}
      {text}
      {unit ? (
        <span className={cn(unit === "×" ? "ml-px" : "ml-[3px]", lighter)}>
          {unit}
        </span>
      ) : null}
    </>
  );
}
