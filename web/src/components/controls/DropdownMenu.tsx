"use client";

import { Check } from "lucide-react";
import { DropdownMenu as DropdownMenuPrimitive } from "radix-ui";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "cn";

import {
  DropdownMenuCheckboxItem as BaseCheckboxItem,
  DropdownMenuContent as BaseContent,
  DropdownMenuItem as BaseItem,
  DropdownMenuLabel as BaseLabel,
  DropdownMenuRadioItem as BaseRadioItem,
  DropdownMenuSeparator as BaseSeparator,
} from "@/components/ui/dropdown-menu";

export {
  DropdownMenu,
  DropdownMenuRadioGroup,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

// A row in the sheet's height and type. Focus, which follows the pointer, shades a row as a chosen
// one is shaded: the accent colour marks a link, not a row.
const ROW =
  "h-[30px] gap-2 rounded-[3px] px-2 py-0 text-cell text-text focus:bg-surface-sunken focus:text-text";

// A chosen row is shaded and ticked at its end; the indicator the base item draws before the label is
// hidden for it.
const CHOOSABLE = cn(
  ROW,
  "pl-2 data-[state=checked]:bg-surface-sunken [&>span:first-child]:hidden",
);

function Tick() {
  return (
    <DropdownMenuPrimitive.ItemIndicator className="ml-auto flex">
      <Check
        aria-hidden="true"
        strokeWidth={2.5}
        className="size-3.5 text-text"
      />
    </DropdownMenuPrimitive.ItemIndicator>
  );
}

export function DropdownMenuContent({
  className,
  align = "start",
  ...props
}: ComponentProps<typeof BaseContent>) {
  return (
    <BaseContent
      align={align}
      className={cn(
        "flex min-w-[220px] flex-col rounded-sm border-border-strong bg-surface-raised p-3 text-text shadow-none",
        className,
      )}
      {...props}
    />
  );
}

type DropdownMenuItemProps = Omit<
  ComponentProps<typeof BaseItem>,
  "variant" | "inset"
> & {
  /** A short note at the row's end. */
  caption?: string;
};

export function DropdownMenuItem({
  caption,
  className,
  children,
  ...props
}: DropdownMenuItemProps) {
  return (
    <BaseItem className={cn(ROW, className)} {...props}>
      <span className="grow whitespace-nowrap">{children}</span>
      {caption ? (
        <>
          {" "}
          <span className="text-caption whitespace-nowrap text-text-subtle">
            {caption}
          </span>
        </>
      ) : null}
    </BaseItem>
  );
}

export function DropdownMenuRadioItem({
  className,
  children,
  ...props
}: ComponentProps<typeof BaseRadioItem>) {
  return (
    <BaseRadioItem className={cn(CHOOSABLE, className)} {...props}>
      <span className="whitespace-nowrap">{children}</span>
      <Tick />
    </BaseRadioItem>
  );
}

export function DropdownMenuCheckboxItem({
  className,
  children,
  ...props
}: ComponentProps<typeof BaseCheckboxItem>) {
  return (
    <BaseCheckboxItem className={cn(CHOOSABLE, className)} {...props}>
      <span className="whitespace-nowrap">{children}</span>
      <Tick />
    </BaseCheckboxItem>
  );
}

export function DropdownMenuLabel({
  className,
  ...props
}: Omit<ComponentProps<typeof BaseLabel>, "inset">) {
  return (
    <BaseLabel
      className={cn(
        "px-2 pt-1 pb-0.5 text-caption font-semibold text-text-subtle",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuSeparator({
  className,
  ...props
}: ComponentProps<typeof BaseSeparator>) {
  return (
    <BaseSeparator
      className={cn("mx-0 my-1 bg-border", className)}
      {...props}
    />
  );
}

// What the choices above it mean or leave out, under a rule at the menu's foot.
export function DropdownMenuNote({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <p className="mt-1 border-t border-border px-2 pt-2 text-caption leading-[1.45] text-text-subtle">
      {children}
    </p>
  );
}
