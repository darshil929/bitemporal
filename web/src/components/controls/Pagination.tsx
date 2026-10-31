import { ChevronLeft, ChevronRight, type LucideIcon } from "lucide-react";
import Link from "next/link";

type PaginationProps = Readonly<{
  page: number;
  pageSize: number;
  /** How many rows the screen matched, of which the pages show up to the row cap. */
  matched: number;
  rowCap: number;
  /** The address showing a page. */
  hrefFor: (page: number) => string;
}>;

const ARROW =
  "inline-flex size-7 shrink-0 items-center justify-center rounded-sm border border-border bg-surface-raised";

function Arrow({
  label,
  icon: Icon,
  href,
}: Readonly<{ label: string; icon: LucideIcon; href: string | null }>) {
  if (href === null) {
    return (
      <span aria-disabled="true" aria-label={label} className={ARROW}>
        <Icon aria-hidden="true" className="size-3.5 text-border-strong" />
      </span>
    );
  }
  return (
    <Link href={href} scroll={false} aria-label={label} className={ARROW}>
      <Icon aria-hidden="true" className="size-3.5 text-text-muted" />
    </Link>
  );
}

// The rows a page shows of those the pages reach, and links to the pages either side; the pages
// stop at the row cap however many rows matched.
export function Pagination({
  page,
  pageSize,
  matched,
  rowCap,
  hrefFor,
}: PaginationProps) {
  const reached = Math.min(matched, rowCap);
  if (reached === 0) {
    return null;
  }
  const first = (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, reached);
  return (
    <nav aria-label="Pages" className="inline-flex items-center gap-2">
      <span className="text-header font-normal text-text-muted tabular-nums">
        Rows {first}–{last} of {reached}
      </span>
      <Arrow
        label="Previous page"
        icon={ChevronLeft}
        href={page > 1 ? hrefFor(page - 1) : null}
      />
      <Arrow
        label="Next page"
        icon={ChevronRight}
        href={last < reached ? hrefFor(page + 1) : null}
      />
    </nav>
  );
}
