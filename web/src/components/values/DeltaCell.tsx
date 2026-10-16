import { NullValue } from "@/components/values/NullValue";
import {
  type Direction,
  direction,
  formatChange,
  formatReturn,
} from "@/lib/format";

import { cn } from "cn";

// Up and down mean price direction alone; a figure that reads as zero takes no colour.
export const DIRECTION_TONES: Record<Direction, string> = {
  up: "text-up",
  down: "text-down",
  flat: "text-text",
};

type DeltaCellProps = Readonly<{
  value: number | null;
  /** A change in rupees, or a return given as a fraction. */
  kind: "change" | "return";
  nullReason: string;
}>;

export function DeltaCell({ value, kind, nullReason }: DeltaCellProps) {
  if (value === null) {
    return (
      <span className="text-cell tabular-nums">
        <NullValue reason={nullReason} />
      </span>
    );
  }
  const formatted =
    kind === "return" ? formatReturn(value) : formatChange(value);
  return (
    <span
      className={cn(
        "text-cell tabular-nums",
        DIRECTION_TONES[direction(formatted)],
      )}
    >
      {formatted.text}
    </span>
  );
}
