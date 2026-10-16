import { Figure } from "@/components/values/Figure";
import { formatPrice, formatShortDate } from "@/lib/format";

type StaleValueProps = Readonly<{
  value: number;
  /** The day the price is from, older than the day the page shows. */
  isoDate: string;
}>;

export function StaleValue({ value, isoDate }: StaleValueProps) {
  return (
    <span className="text-cell text-text tabular-nums">
      <span className="mr-1.5 text-caption font-medium text-text-muted">
        {formatShortDate(isoDate)}
      </span>
      <Figure formatted={formatPrice(value)} />
    </span>
  );
}
