import type { ComponentProps } from "react";

import { cn } from "cn";

import { Button as BaseButton } from "@/components/ui/button";

const KINDS = {
  primary: "border-text bg-text text-surface",
  secondary:
    "border-border bg-surface-raised text-text [&_svg]:text-text-muted",
  ghost: "border-transparent bg-transparent text-text-muted",
} as const;

// The dot pulsing beside a busy button's label, in its ink.
const BUSY_DOTS = {
  primary: "bg-surface",
  secondary: "bg-text-muted",
  ghost: "bg-text-muted",
} as const;

export type ButtonKind = keyof typeof KINDS;

type ButtonProps = Omit<
  ComponentProps<typeof BaseButton>,
  "variant" | "size" | "asChild"
> & {
  kind?: ButtonKind;
  /** Its action is under way: held in its colours, its label naming the action. */
  isBusy?: boolean;
};

export function Button({
  kind = "secondary",
  isBusy = false,
  disabled,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <BaseButton
      variant={null}
      size={null}
      disabled={disabled || isBusy}
      aria-busy={isBusy || undefined}
      className={cn(
        "h-control gap-1.5 rounded-sm border px-3 text-cell font-medium disabled:opacity-100 [&_svg:not([class*='size-'])]:size-3.5",
        KINDS[kind],
        isBusy
          ? "gap-2"
          : "disabled:border-border disabled:bg-surface-sunken disabled:text-text-subtle disabled:[&_svg]:text-text-subtle",
        className,
      )}
      {...props}
    >
      {isBusy ? (
        <span
          aria-hidden="true"
          className={cn(
            "size-1.5 shrink-0 rounded-full motion-safe:animate-pulse",
            BUSY_DOTS[kind],
          )}
        />
      ) : null}
      {children}
    </BaseButton>
  );
}
