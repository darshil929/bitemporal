import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "cn";

export type StatusTone = "neutral" | "flag";

type StatusPillProps = Readonly<{
  tone?: StatusTone;
  icon?: LucideIcon;
  children: ReactNode;
}>;

// A state of the thing beside it, in words; flag is the only attention colour.
export function StatusPill({
  tone = "neutral",
  icon: Glyph,
  children,
}: StatusPillProps) {
  return (
    <span
      data-tone={tone}
      className={cn(
        "inline-flex h-[22px] items-center gap-[5px] rounded-[3px] border px-2 text-caption font-medium whitespace-nowrap",
        tone === "flag"
          ? "border-flag-border bg-flag-surface text-flag"
          : "border-border bg-surface-sunken text-text-muted",
      )}
    >
      {Glyph ? (
        <Glyph aria-hidden="true" strokeWidth={2.2} className="size-3" />
      ) : null}
      {children}
    </span>
  );
}
