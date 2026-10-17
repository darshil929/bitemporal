import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "cn";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/controls/DropdownMenu";

type SelectProps = Readonly<{
  /** A word before the value naming what is chosen, such as "View". */
  prefix?: string;
  /** What is chosen, as the field shows it. */
  value: string;
  /** The menu's rows. */
  children: ReactNode;
  className?: string;
  menuClassName?: string;
}>;

// A field showing a choice that opens a menu of the others; its border takes the focus colour while
// the menu is open.
export function Select({
  prefix,
  value,
  children,
  className,
  menuClassName,
}: SelectProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          "inline-flex h-control items-center gap-1.5 rounded-sm border border-border bg-surface-raised px-2.5 text-cell whitespace-nowrap text-text outline-none focus-visible:border-accent data-[state=open]:border-accent",
          className,
        )}
      >
        {prefix ? (
          <>
            <span className="text-text-subtle">{prefix}</span>{" "}
          </>
        ) : null}
        <span className="grow text-left font-medium">{value}</span>
        <ChevronDown aria-hidden="true" className="size-3.5 text-text-subtle" />
      </DropdownMenuTrigger>
      <DropdownMenuContent className={menuClassName}>
        {children}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
