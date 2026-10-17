import type { ReactNode } from "react";

import { PageFooter } from "@/components/layout/PageFooter";

// Pages reached before signing in: each brings its own header, with no navigation in it.
export default function SignedOutLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <div className="flex min-h-screen flex-col">
      {children}
      <div className="mt-auto px-gutter pb-gutter">
        <PageFooter />
      </div>
    </div>
  );
}
