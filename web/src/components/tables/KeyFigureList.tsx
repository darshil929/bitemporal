import type { ReactNode } from "react";

import { cn } from "cn";

export type KeyFigure = Readonly<{ label: string; value: ReactNode }>;

type KeyFigureListProps = Readonly<{
  title?: string;
  /** Beside the title: the venue and day the figures are from. */
  caption: ReactNode;
  figures: readonly KeyFigure[];
  /** Where the figures come from, under them. */
  sources: ReactNode;
  className?: string;
}>;

// A day's figures as label and value rows, edge to edge between rules.
export function KeyFigureList({
  title = "Key figures",
  caption,
  figures,
  sources,
  className,
}: KeyFigureListProps) {
  return (
    <section
      className={cn(
        "flex flex-col self-start rounded-sm border border-border bg-surface-raised",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 px-card py-3.5">
        <h2 className="text-heading text-text">{title}</h2>
        <span className="text-caption text-text-subtle">{caption}</span>
      </div>
      <dl>
        {figures.map((figure) => (
          <div
            key={figure.label}
            className="flex h-8 items-center justify-between gap-3 border-t border-border px-card"
          >
            <dt className="text-cell text-text-muted">{figure.label}</dt>
            <dd className="text-cell text-text tabular-nums">{figure.value}</dd>
          </div>
        ))}
      </dl>
      <p className="border-t border-border px-card py-3 text-caption leading-[1.5] text-text-subtle">
        {sources}
      </p>
    </section>
  );
}
