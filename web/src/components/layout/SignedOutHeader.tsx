import type { ReactNode } from "react";

// The wordmark alone, and what the page says beside it, such as the setup's steps.
export function SignedOutHeader({
  children,
}: Readonly<{ children?: ReactNode }>) {
  return (
    <header className="flex h-14 items-center gap-8 border-b border-border bg-surface px-gutter">
      <span className="text-heading tracking-[-0.01em] text-text">
        Bitemporal
      </span>
      {children}
    </header>
  );
}
