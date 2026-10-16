import Link from "next/link";

type InstrumentCellProps = Readonly<{
  displayName: string;
  symbol: string;
  isin: string;
  /** The ISIN beside the symbol, where the symbol alone does not tell instruments apart. */
  showIsin?: boolean;
}>;

// The name opens the instrument's page; a long one is cut short rather than wrapped.
export function InstrumentCell({
  displayName,
  symbol,
  isin,
  showIsin = false,
}: InstrumentCellProps) {
  return (
    <div className="flex min-w-0 flex-col gap-px">
      <Link
        href={`/instrument/${isin}`}
        className="truncate text-cell font-medium text-text"
      >
        {displayName}
      </Link>
      <span className="font-mono text-caption text-text-subtle">
        {showIsin ? `${symbol} · ${isin}` : symbol}
      </span>
    </div>
  );
}
