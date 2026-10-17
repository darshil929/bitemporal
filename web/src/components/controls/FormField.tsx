import { TriangleAlert } from "lucide-react";
import { type ReactNode, useId } from "react";

export type FieldControl = Readonly<{
  id: string;
  label: string;
  isInvalid: boolean;
  "aria-describedby"?: string;
}>;

type FormFieldProps = Readonly<{
  label: string;
  /** Beside the label, such as who changes a value shown read-only. */
  aside?: string;
  /** The rule the value keeps, stated before anything is typed. */
  help?: string;
  /** What is wrong with the value, in place of the help. */
  error?: string;
  /** The field's control, given its id, name and the message that describes it. */
  children: (control: FieldControl) => ReactNode;
}>;

// A label above its control, then the error where there is one, otherwise the help.
export function FormField({
  label,
  aside,
  help,
  error,
  children,
}: FormFieldProps) {
  const id = useId();
  const message = error ?? help;
  const messageId = `${id}-message`;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-header text-text-muted">
          {label}
        </label>
        {aside ? (
          <span className="text-caption text-text-subtle">{aside}</span>
        ) : null}
      </div>
      {children({
        id,
        label,
        isInvalid: error !== undefined,
        "aria-describedby": message ? messageId : undefined,
      })}
      {error ? (
        <p
          id={messageId}
          className="flex items-start gap-[5px] text-header leading-[1.4] font-normal text-flag"
        >
          <TriangleAlert aria-hidden="true" className="mt-px size-3 shrink-0" />
          {error}
        </p>
      ) : help ? (
        <p
          id={messageId}
          className="text-header leading-[1.4] font-normal text-text-subtle"
        >
          {help}
        </p>
      ) : null}
    </div>
  );
}
