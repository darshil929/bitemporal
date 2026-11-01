import type { ReactNode } from "react";

import { cn } from "cn";

type StatProps = Readonly<{
  label: string;
  /** A square in the colour the counted instruments take in the breadth bar. */
  keyColour?: "up" | "down" | "neutral";
  children: ReactNode;
}>;

const KEYS = {
  up: "bg-up",
  down: "bg-down",
  neutral: "bg-border-strong",
} as const;

// A summary figure under its label, one term of the list it sits in.
export function Stat({ label, keyColour, children }: StatProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="flex items-center gap-[5px] text-header font-normal text-text-muted">
        {keyColour ? (
          <span aria-hidden="true" className={cn("size-2", KEYS[keyColour])} />
        ) : null}
        {label}
      </dt>
      <dd className="text-summary text-text tabular-nums">{children}</dd>
    </div>
  );
}
