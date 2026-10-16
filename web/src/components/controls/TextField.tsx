import type { ComponentProps } from "react";

import { cn } from "cn";

type TextFieldProps = Omit<ComponentProps<"input">, "aria-label"> & {
  /** What the field holds, read out in place of a visible label. */
  label: string;
  /** A unit after the value, inside the field. */
  unit?: string;
};

// A short value such as a criterion's threshold, in tabular figures; the field's border, not the
// input's, takes the focus colour, since the unit sits inside it.
export function TextField({
  label,
  unit,
  className,
  ...props
}: TextFieldProps) {
  return (
    <span
      className={cn(
        "inline-flex h-control items-center justify-between gap-1.5 rounded-sm border border-border bg-surface px-2.5 text-cell text-text tabular-nums focus-within:border-accent",
        className,
      )}
    >
      <input
        aria-label={label}
        className="w-full min-w-0 bg-transparent outline-none"
        {...props}
      />
      {unit ? <span className="text-text-subtle">{unit}</span> : null}
    </span>
  );
}
