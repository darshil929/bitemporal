"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { createQueryClient } from "@/lib/query";

// One cache for the browser tab, kept across renders.
export function QueryProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [client] = useState(createQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
