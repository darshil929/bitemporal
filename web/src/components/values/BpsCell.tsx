import { TriangleAlert } from "lucide-react";

import { Figure } from "@/components/values/Figure";
import { NullValue } from "@/components/values/NullValue";
import { formatBps } from "@/lib/format";

type BpsCellProps = Readonly<{
  value: number | null;
  /** The two venues' closes diverge, both having traded enough for their gap to mean something. */
  isDiverging: boolean;
  nullReason: string;
}>;

// The spread shows whatever its size; only a divergence carries the flag, and inside it the unit
// reads in the flag's colour so the whole figure keeps its contrast.
export function BpsCell({ value, isDiverging, nullReason }: BpsCellProps) {
  if (value === null) {
    return (
      <span className="text-cell tabular-nums">
        <NullValue reason={nullReason} />
      </span>
    );
  }
  if (!isDiverging) {
    return (
      <span className="text-cell text-text tabular-nums">
        <Figure formatted={formatBps(value)} />
      </span>
    );
  }
  return (
    <span className="inline-flex h-[22px] items-center gap-1 rounded-[3px] border border-flag-border bg-flag-surface px-1.5 text-cell text-flag tabular-nums">
      <TriangleAlert aria-hidden="true" className="size-[11px]" />
      <span className="sr-only">Diverging: </span>
      <Figure formatted={formatBps(value)} isUnitLighter={false} />
    </span>
  );
}
