import type { LucideIcon } from "lucide-react";
import type { ComponentProps } from "react";

import { cn } from "cn";

import { Button as BaseButton } from "@/components/ui/button";

const KINDS = {
  bordered: {
    box: "size-control border-border bg-surface-raised text-text-muted",
    glyph: "size-[15px]",
  },
  plain: {
    box: "size-6 border-transparent bg-transparent text-text-subtle",
    glyph: "size-4",
  },
} as const;

export type IconButtonKind = keyof typeof KINDS;

type IconButtonProps = Omit<
  ComponentProps<typeof BaseButton>,
  "variant" | "size" | "children" | "aria-label"
> & {
  icon: LucideIcon;
  /** What pressing it does, read out in place of a text label. */
  label: string;
  kind?: IconButtonKind;
};

// A glyph alone: bordered where it stands by itself, plain where a row offers it.
export function IconButton({
  icon: Glyph,
  label,
  kind = "bordered",
  className,
  ...props
}: IconButtonProps) {
  return (
    <BaseButton
      variant={null}
      size={null}
      aria-label={label}
      className={cn("rounded-sm border", KINDS[kind].box, className)}
      {...props}
    >
      <Glyph aria-hidden="true" className={KINDS[kind].glyph} />
    </BaseButton>
  );
}
