import type { ReactNode } from "react";

import type { StatusTone } from "@/components/status/StatusPill";

import { cn } from "cn";

type NoteChipProps = Readonly<{
  tone?: StatusTone;
  children: ReactNode;
}>;

// A short note beside a name or a figure, smaller and quieter than a status.
export function NoteChip({ tone = "neutral", children }: NoteChipProps) {
  return (
    <span
      data-tone={tone}
      className={cn(
        "inline-flex h-5 items-center rounded-[3px] border px-1.5 text-caption whitespace-nowrap",
        tone === "flag"
          ? "border-flag-border bg-flag-surface text-flag"
          : "border-border bg-surface-sunken text-text-muted",
      )}
    >
      {children}
    </span>
  );
}
