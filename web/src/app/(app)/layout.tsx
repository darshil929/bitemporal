import type { ReactNode } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { requireSession } from "@/lib/page-access";

export default async function SignedInLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  await requireSession();
  return <AppShell>{children}</AppShell>;
}
