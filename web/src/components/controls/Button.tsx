import type { ComponentProps } from "react";

import { cn } from "cn";

import { Button as BaseButton } from "@/components/ui/button";

const KINDS = {
  primary: "border-text bg-text text-surface",
  secondary:
    "border-border bg-surface-raised text-text [&_svg]:text-text-muted",
  ghost: "border-transparent bg-transparent text-text-muted",
} as const;

export type ButtonKind = keyof typeof KINDS;

type ButtonProps = Omit<
  ComponentProps<typeof BaseButton>,
  "variant" | "size"
> & {
  kind?: ButtonKind;
};

export function Button({
  kind = "secondary",
  className,
  ...props
}: ButtonProps) {
  return (
    <BaseButton
      variant={null}
      size={null}
      className={cn(
        "h-control gap-1.5 rounded-sm border px-3 text-cell font-medium [&_svg:not([class*='size-'])]:size-3.5",
        KINDS[kind],
        "disabled:border-border disabled:bg-surface-sunken disabled:text-text-subtle disabled:opacity-100 disabled:[&_svg]:text-text-subtle",
        className,
      )}
      {...props}
    />
  );
}
