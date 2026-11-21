"use client";

import { TriangleAlert } from "lucide-react";

import { Button } from "@/components/controls/Button";
import { Dialog, DialogActions } from "@/components/layout/Dialog";

type ConfirmDialogProps = Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  /** Each concrete effect of confirming, listed plainly before the action runs. */
  changes: readonly string[];
  confirmLabel: string;
  busyLabel?: string;
  cancelLabel?: string;
  isBusy?: boolean;
  error?: string | null;
  onConfirm: () => void;
}>;

// A confirmation listing what changes before the action is taken, using the primary button.
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  changes,
  confirmLabel,
  busyLabel,
  cancelLabel = "Cancel",
  isBusy = false,
  error = null,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      width="medium"
      canClose={!isBusy}
      footer={
        <DialogActions
          right={
            <>
              <Button
                type="button"
                kind="secondary"
                disabled={isBusy}
                onClick={() => onOpenChange(false)}
              >
                {cancelLabel}
              </Button>
              <Button
                type="button"
                kind="primary"
                isBusy={isBusy}
                onClick={onConfirm}
              >
                {isBusy && busyLabel ? busyLabel : confirmLabel}
              </Button>
            </>
          }
        />
      }
    >
      <p className="text-cell leading-normal text-text-muted">{description}</p>
      <ul className="flex flex-col gap-2">
        {changes.map((change) => (
          <li
            key={change}
            className="flex gap-2.5 text-cell leading-[1.45] text-text"
          >
            <span
              aria-hidden="true"
              className="w-[3px] shrink-0 rounded-[2px] bg-border-strong"
            />
            <span>{change}</span>
          </li>
        ))}
      </ul>
      {error ? (
        <p
          role="alert"
          className="flex items-start gap-1.5 text-header leading-[1.4] font-normal text-flag"
        >
          <TriangleAlert
            aria-hidden="true"
            className="mt-0.5 size-3.5 shrink-0"
          />
          {error}
        </p>
      ) : null}
    </Dialog>
  );
}
