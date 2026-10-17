import type { ReactNode } from "react";

import { InstrumentSearch } from "@/components/controls/InstrumentSearch";
import { AccountMenu } from "@/components/layout/AccountMenu";
import { ShellNavigation } from "@/components/layout/ShellNavigation";
import type { SignedInPerson } from "@/lib/page-access";

export function AppShell({
  person,
  children,
}: Readonly<{ person: SignedInPerson; children: ReactNode }>) {
  return (
    <>
      <header className="flex h-14 items-center gap-8 border-b border-border bg-surface px-gutter">
        <span className="text-heading tracking-[-0.01em] text-text">
          Bitemporal
        </span>
        <ShellNavigation />
        <div className="ml-auto flex items-center gap-2.5">
          <InstrumentSearch shortcutKey="/" className="w-70" />
          <AccountMenu person={person} />
        </div>
      </header>
      <main className="flex flex-col gap-section p-gutter">{children}</main>
    </>
  );
}
