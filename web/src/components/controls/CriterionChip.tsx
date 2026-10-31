import { Lock, X } from "lucide-react";
import Link from "next/link";

import {
  COMPARISONS,
  type Criterion,
  FIGURES,
  thresholdText,
} from "@/lib/screener-criteria";

import { cn } from "cn";

type CriterionChipProps = Readonly<{
  criterion: Criterion;
  /** The liquidity gate, a criterion the screen starts with, on the sunken surface. */
  isGate?: boolean;
  /** The screen's address without this criterion. */
  removeHref: string;
}>;

/** How a criterion reads aloud: `Return 3M above 0.00%`. */
export function describeCriterion(criterion: Criterion): string {
  const { label } = FIGURES[criterion.figure];
  const { words } = COMPARISONS[criterion.comparison];
  return `${label} ${words} ${thresholdText(criterion)}`;
}

// A filter that is also a column: the figure, the comparison's sign and the threshold, removed by
// a link to the screen without it, so the address stays the view.
export function CriterionChip({
  criterion,
  isGate = false,
  removeHref,
}: CriterionChipProps) {
  const described = describeCriterion(criterion);
  return (
    <span
      role="group"
      aria-label={isGate ? `Liquidity gate, ${described}` : described}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-sm border pr-1.5 pl-2.5 text-header font-normal whitespace-nowrap",
        isGate
          ? "border-border bg-surface-sunken"
          : "border-border-strong bg-surface-raised",
      )}
    >
      {isGate ? (
        <Lock aria-hidden="true" className="size-3 text-text-muted" />
      ) : null}
      <span className="text-text-muted">{FIGURES[criterion.figure].label}</span>
      <span className="text-text-subtle">
        {COMPARISONS[criterion.comparison].sign}
      </span>
      <span className="font-medium text-text tabular-nums">
        {thresholdText(criterion)}
      </span>
      <Link
        href={removeHref}
        scroll={false}
        aria-label={
          isGate ? "Remove the liquidity gate" : `Remove ${described}`
        }
        className="inline-flex size-[18px] items-center justify-center text-text-subtle"
      >
        <X aria-hidden="true" className="size-3" />
      </Link>
    </span>
  );
}
