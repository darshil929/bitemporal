import { Search } from "lucide-react";
import type { ComponentProps } from "react";

import { cn } from "cn";

type SearchFieldProps = Omit<ComponentProps<"input">, "type" | "aria-label"> & {
  /** What is searched, read out in place of a visible label. */
  label: string;
};

// The browser's own clear button is not drawn, so it is hidden.
export function SearchField({ label, className, ...props }: SearchFieldProps) {
  return (
    <span
      className={cn(
        "flex h-control items-center gap-2 rounded-sm border border-border bg-surface px-2.5 focus-within:border-accent",
        className,
      )}
    >
      <Search
        aria-hidden="true"
        className="size-3.5 shrink-0 text-text-subtle"
      />
      <input
        type="search"
        aria-label={label}
        className="min-w-0 grow bg-transparent text-cell text-text outline-none placeholder:text-text-subtle [&::-webkit-search-cancel-button]:appearance-none"
        {...props}
      />
    </span>
  );
}
