import { DIRECTION_TONES } from "@/components/values/DeltaCell";
import { NullValue } from "@/components/values/NullValue";
import {
  type Formatted,
  direction,
  formatChange,
  formatPrice,
  formatReturn,
} from "@/lib/format";

import { cn } from "cn";

type HeroFigureProps = Readonly<{
  /** The close as traded, the one figure a page leads with. */
  close: number | null;
  change: number | null;
  /** The return as a fraction. */
  returnFraction: number | null;
  nullReason: string;
}>;

function Movement({
  formatted,
  nullReason,
}: Readonly<{ formatted: Formatted | null; nullReason: string }>) {
  return (
    <span
      className={cn(
        "text-body font-medium tabular-nums",
        formatted && DIRECTION_TONES[direction(formatted)],
      )}
    >
      {formatted ? formatted.text : <NullValue reason={nullReason} />}
    </span>
  );
}

// The lead figure keeps proportional figures; its change and return beside it are tabular.
export function HeroFigure({
  close,
  change,
  returnFraction,
  nullReason,
}: HeroFigureProps) {
  const price = close === null ? null : formatPrice(close);
  return (
    <div className="flex items-baseline gap-3">
      <span className="text-hero text-text">
        {price === null ? (
          <NullValue reason={nullReason} />
        ) : (
          <>
            <span className="font-medium text-text-subtle">{price.prefix}</span>
            {price.text}
          </>
        )}
      </span>
      <Movement
        formatted={change === null ? null : formatChange(change)}
        nullReason={nullReason}
      />
      <Movement
        formatted={
          returnFraction === null ? null : formatReturn(returnFraction)
        }
        nullReason={nullReason}
      />
    </div>
  );
}
