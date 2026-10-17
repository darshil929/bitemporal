import type { ComponentProps } from "react";

import { cn } from "cn";

type FieldState = Readonly<{
  /** The value breaks a rule the field states. */
  isInvalid?: boolean;
  /** The value is shown but changed elsewhere. */
  isReadOnly?: boolean;
}>;

// A field's box: its border, not the input's, takes the focus colour, since a unit or a control sits
// inside it; a broken rule takes the flag, and a value changed elsewhere sits on the sunken surface.
export function fieldBox({
  isInvalid = false,
  isReadOnly = false,
}: FieldState) {
  return cn(
    "inline-flex h-control items-center gap-1.5 rounded-sm border px-2.5 text-cell",
    isInvalid ? "border-flag" : "border-border focus-within:border-accent",
    isReadOnly ? "bg-surface-sunken text-text-muted" : "bg-surface text-text",
  );
}

type TextFieldProps = Omit<ComponentProps<"input">, "aria-label"> & {
  /** What the field holds, read out in place of a visible label. */
  label: string;
  /** A unit after the value, inside the field. */
  unit?: string;
  isInvalid?: boolean;
};

// A short value in tabular figures, such as a criterion's threshold, or a form's text.
export function TextField({
  label,
  unit,
  isInvalid = false,
  readOnly,
  className,
  ...props
}: TextFieldProps) {
  return (
    <span
      className={cn(
        fieldBox({ isInvalid, isReadOnly: readOnly }),
        "justify-between tabular-nums",
        className,
      )}
    >
      <input
        aria-label={label}
        aria-invalid={isInvalid || undefined}
        readOnly={readOnly}
        className="w-full min-w-0 bg-transparent outline-none"
        {...props}
      />
      {unit ? <span className="text-text-subtle">{unit}</span> : null}
    </span>
  );
}
