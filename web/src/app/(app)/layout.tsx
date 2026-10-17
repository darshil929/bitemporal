import type { ReactNode } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { requireSession } from "@/lib/page-access";

export default async function SignedInLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  const person = await requireSession();
  return <AppShell person={person}>{children}</AppShell>;
}
