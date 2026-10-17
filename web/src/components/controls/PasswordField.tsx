"use client";

import { Eye, EyeOff } from "lucide-react";
import { type ComponentProps, useState } from "react";

import { cn } from "cn";

import { fieldBox } from "@/components/controls/TextField";

type PasswordFieldProps = Omit<
  ComponentProps<"input">,
  "type" | "aria-label"
> & {
  /** What the field holds, read out in place of a visible label. */
  label: string;
  isInvalid?: boolean;
};

// Hidden as it is typed; the eye shows the characters, in the mono face so each one reads apart.
export function PasswordField({
  label,
  isInvalid = false,
  className,
  ...props
}: PasswordFieldProps) {
  const [isShown, setShown] = useState(false);
  const Glyph = isShown ? EyeOff : Eye;
  return (
    <span className={cn(fieldBox({ isInvalid }), "gap-2 pr-1.5", className)}>
      <input
        type={isShown ? "text" : "password"}
        aria-label={label}
        aria-invalid={isInvalid || undefined}
        className={cn(
          "min-w-0 grow bg-transparent outline-none",
          isShown && "font-mono",
        )}
        {...props}
      />
      <button
        type="button"
        aria-label={isShown ? "Hide password" : "Show password"}
        onClick={() => setShown((shown) => !shown)}
        className="inline-flex size-6 shrink-0 items-center justify-center rounded-xs text-text-muted"
      >
        <Glyph aria-hidden="true" className="size-[15px]" />
      </button>
    </span>
  );
}
