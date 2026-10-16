import { Figure } from "@/components/values/Figure";
import { NullValue } from "@/components/values/NullValue";
import {
  formatDeliveryShare,
  formatLargeValue,
  formatMultiple,
  formatVolume,
} from "@/lib/format";

const FORMATS = {
  large_value: formatLargeValue,
  volume: formatVolume,
  multiple: formatMultiple,
  delivery_share: formatDeliveryShare,
} as const;

type CompactValueProps = Readonly<{
  value: number | null;
  /** Rupees in lakh or crore, a count of shares, a multiple, or a delivery share in percent. */
  kind: keyof typeof FORMATS;
  nullReason: string;
}>;

export function CompactValue({ value, kind, nullReason }: CompactValueProps) {
  return (
    <span className="text-cell text-text tabular-nums">
      {value === null ? (
        <NullValue reason={nullReason} />
      ) : (
        <Figure formatted={FORMATS[kind](value)} />
      )}
    </span>
  );
}
