import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "cn";

export type Segment = Readonly<{
  label: string;
  /** The address showing this choice; the selection is carried in it. */
  href: string;
  isSelected?: boolean;
  /** Shown but not offered. */
  isDisabled?: boolean;
  /** A mark after the label, such as the primary venue's. */
  marker?: ReactNode;
}>;

type SegmentedControlProps = Readonly<{
  /** What the choice is of, read out before its options. */
  label: string;
  segments: readonly Segment[];
}>;

const SEGMENT =
  "flex h-[26px] items-center gap-1.5 rounded-[3px] border px-3 text-cell font-medium";

// The venue an instrument's pages open on, marked as its badge marks it.
export function PrimaryMark() {
  return (
    <>
      <span aria-hidden="true" className="size-1.5 rounded-full bg-text" />
      <span className="sr-only">(primary)</span>
    </>
  );
}

// One choice among a few, each a link, so a choice is an address that can be shared and the page
// stays where it is scrolled to.
export function SegmentedControl({ label, segments }: SegmentedControlProps) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex items-center gap-0.5 rounded-sm border border-border bg-surface-sunken p-0.5"
    >
      {segments.map((segment) =>
        segment.isDisabled ? (
          <span
            key={segment.label}
            aria-disabled="true"
            className={cn(SEGMENT, "border-transparent text-border-strong")}
          >
            {segment.label}
            {segment.marker ? " " : null}
            {segment.marker}
          </span>
        ) : (
          <Link
            key={segment.label}
            href={segment.href}
            scroll={false}
            aria-current={segment.isSelected ? "true" : undefined}
            className={cn(
              SEGMENT,
              segment.isSelected
                ? "border-border bg-surface text-text"
                : "border-transparent text-text-muted",
            )}
          >
            {segment.label}
            {segment.marker ? " " : null}
            {segment.marker}
          </Link>
        ),
      )}
    </div>
  );
}
