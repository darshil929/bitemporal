import type { ReactNode } from "react";

import { cn } from "cn";

type RefetchProps = Readonly<{
  isRefetching: boolean;
  children: ReactNode;
}>;

// Holds the previous result in place, at half opacity, while the next one loads.
export function Refetch({ isRefetching, children }: RefetchProps) {
  return (
    <div aria-busy={isRefetching} className="relative">
      {isRefetching ? (
        <div className="absolute inset-x-0 top-0 z-10 h-0.5 bg-accent" />
      ) : null}
      <div className={cn(isRefetching && "opacity-50")}>{children}</div>
    </div>
  );
}
