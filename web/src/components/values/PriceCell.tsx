import { Skeleton } from "@/components/layout/Skeleton";
import { Figure } from "@/components/values/Figure";
import { NullValue } from "@/components/values/NullValue";
import { formatPrice } from "@/lib/format";

type PriceCellProps = Readonly<{
  value: number | null;
  /** What an absent price means here, shown with its dash. */
  nullReason: string;
  isLoading?: boolean;
}>;

export function PriceCell({
  value,
  nullReason,
  isLoading = false,
}: PriceCellProps) {
  if (isLoading) {
    return <Skeleton className="h-[11px] w-[72px]" />;
  }
  return (
    <span className="text-cell text-text tabular-nums">
      {value === null ? (
        <NullValue reason={nullReason} />
      ) : (
        <Figure formatted={formatPrice(value)} />
      )}
    </span>
  );
}
