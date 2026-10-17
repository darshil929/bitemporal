import type { ReactNode } from "react";

import { InstrumentSearch } from "@/components/controls/InstrumentSearch";
import { ShellNavigation } from "@/components/layout/ShellNavigation";

export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <>
      <header className="flex h-14 items-center gap-8 border-b border-border bg-surface px-gutter">
        <span className="text-heading tracking-[-0.01em] text-text">
          Bitemporal
        </span>
        <ShellNavigation />
        <InstrumentSearch shortcutKey="/" className="ml-auto w-80" />
      </header>
      <main className="flex flex-col gap-section p-gutter">{children}</main>
    </>
  );
}
