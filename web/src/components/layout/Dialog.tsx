"use client";

import { X } from "lucide-react";
import { Dialog as DialogPrimitive } from "radix-ui";
import type { ReactNode } from "react";

import { IconButton } from "@/components/controls/IconButton";
import {
  Dialog as BaseDialog,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "cn";

const WIDTHS = {
  narrow: "max-w-[460px]",
  medium: "max-w-[480px]",
  wide: "max-w-[560px]",
} as const;

export type DialogWidth = keyof typeof WIDTHS;

type DialogProps = Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  subtitle?: string;
  footer?: ReactNode;
  width?: DialogWidth;
  /** False while an action inside the dialog is running, preventing dismissal. */
  canClose?: boolean;
  children: ReactNode;
}>;

// A modal surface raised over the page under a translucent surface overlay.
export function Dialog({
  open,
  onOpenChange,
  title,
  subtitle,
  footer,
  width = "medium",
  canClose = true,
  children,
}: DialogProps) {
  function handleOpenChange(next: boolean) {
    if (next || canClose) {
      onOpenChange(next);
    }
  }

  return (
    <BaseDialog open={open} onOpenChange={handleOpenChange}>
      <DialogPortal>
        <DialogOverlay className="bg-surface/75" />
        <DialogPrimitive.Content
          aria-describedby={subtitle ? undefined : undefined}
          onEscapeKeyDown={(event) => {
            if (!canClose) event.preventDefault();
          }}
          onPointerDownOutside={(event) => {
            if (!canClose) event.preventDefault();
          }}
          className={cn(
            "fixed top-[50%] left-[50%] z-50 w-[calc(100%-2rem)] translate-x-[-50%] translate-y-[-50%] overflow-hidden rounded-sm border border-border-strong bg-surface-raised outline-none",
            WIDTHS[width],
          )}
        >
          <div className="flex items-start justify-between gap-4 px-5 pt-4">
            <div className="flex flex-col gap-1">
              <DialogTitle className="text-heading leading-normal text-text">
                {title}
              </DialogTitle>
              {subtitle ? (
                <DialogDescription className="text-header leading-[1.45] font-normal text-text-muted">
                  {subtitle}
                </DialogDescription>
              ) : null}
            </div>
            <IconButton
              icon={X}
              label="Close"
              kind="plain"
              disabled={!canClose}
              onClick={() => handleOpenChange(false)}
              className="size-7 shrink-0"
            />
          </div>
          <div className="flex flex-col gap-4 px-5 pt-4 pb-5">{children}</div>
          {footer ? (
            <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-3">
              {footer}
            </div>
          ) : null}
        </DialogPrimitive.Content>
      </DialogPortal>
    </BaseDialog>
  );
}

/** Footer slots of a dialog, keeping secondary controls opposite the primary action. */
export function DialogActions({
  left,
  right,
}: Readonly<{ left?: ReactNode; right?: ReactNode }>) {
  return (
    <>
      <div className="flex items-center gap-2">{left}</div>
      <div className="flex items-center gap-2">{right}</div>
    </>
  );
}
