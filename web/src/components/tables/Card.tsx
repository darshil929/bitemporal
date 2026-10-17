import type { ReactNode } from "react";

import { cn } from "cn";

type CardProps = Readonly<{
  title: string;
  /** A line under the title: what the card covers, or how to read it. */
  caption?: ReactNode;
  /** Beside the title, such as a link or a provenance chip. */
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}>;

// A titled group of figures, raised from the page.
export function Card({
  title,
  caption,
  aside,
  children,
  className,
}: CardProps) {
  return (
    <section
      className={cn(
        "flex flex-col gap-3 rounded-sm border border-border bg-surface-raised p-card",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h2 className="text-heading text-text">{title}</h2>
          {caption ? (
            <p className="text-header leading-[1.45] font-normal text-text-subtle">
              {caption}
            </p>
          ) : null}
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}
