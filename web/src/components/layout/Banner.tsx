import type { ReactNode } from "react";

import { Info, TriangleAlert } from "lucide-react";

import { cn } from "cn";

type BannerProps = Readonly<{
  tone?: "flag" | "neutral";
  children: ReactNode;
  action?: ReactNode;
}>;

// A flag banner says what qualifies the figures on the page; a neutral one states how to read them.
export function Banner({ tone = "flag", children, action }: BannerProps) {
  const Glyph = tone === "flag" ? TriangleAlert : Info;
  return (
    <div
      data-tone={tone}
      className={cn(
        "flex items-center gap-2.5 rounded-sm border px-3.5 py-2.5",
        tone === "flag"
          ? "border-flag-border bg-flag-surface"
          : "border-border bg-surface-sunken",
      )}
    >
      <Glyph
        aria-hidden="true"
        className={cn(
          "size-4 shrink-0",
          tone === "flag" ? "text-flag" : "text-text-muted",
        )}
      />
      <div className="grow text-cell leading-[1.45] text-text">{children}</div>
      {action}
    </div>
  );
}
