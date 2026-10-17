"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/controls/Button";
import { FormField } from "@/components/controls/FormField";
import { PasswordField } from "@/components/controls/PasswordField";
import { apiClient } from "@/lib/api-client";
import { PASSWORD_PROBLEMS, PASSWORDS_DIFFER } from "@/lib/password-rule";

type NewPasswordFormProps = Readonly<{
  displayName: string;
  /** The address to open once the password is replaced, already held to this site. */
  next: string;
}>;

type Errors = Readonly<{ password?: string; again?: string; form?: string }>;

// A temporary password is replaced by one the person chooses before any page opens.
export function NewPasswordForm({ displayName, next }: NewPasswordFormProps) {
  const router = useRouter();
  const [errors, setErrors] = useState<Errors>({});
  const [isBusy, setBusy] = useState(false);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password"));
    if (password !== String(form.get("again"))) {
      setErrors({ again: PASSWORDS_DIFFER });
      return;
    }
    setErrors({});
    setBusy(true);
    const { error, response } = await apiClient.POST("/auth/password", {
      body: { password },
    });
    // A password already replaced, here or meanwhile elsewhere, leaves nothing to choose.
    if (response.ok || response.status === 409) {
      router.replace(next);
      router.refresh();
      return;
    }
    setBusy(false);
    const problem =
      typeof error?.detail === "string"
        ? PASSWORD_PROBLEMS[error.detail]
        : undefined;
    setErrors(
      problem
        ? { password: problem }
        : { form: "The password could not be saved. Try again." },
    );
  }

  return (
    <form
      onSubmit={save}
      className="flex w-[400px] flex-col gap-4 rounded-sm border border-border bg-surface-raised p-6"
    >
      <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-text">
        Choose a new password
      </h1>
      <p className="text-cell leading-normal text-text-muted">
        {displayName} signed in with a temporary password. A new password
        replaces it before any page opens.
      </p>
      <FormField
        label="New password"
        help="At least 15 characters"
        error={errors.password}
      >
        {({ isInvalid, ...control }) => (
          <PasswordField
            name="password"
            required
            autoComplete="new-password"
            isInvalid={isInvalid}
            className="w-full"
            {...control}
          />
        )}
      </FormField>
      <FormField label="New password again" error={errors.again}>
        {({ isInvalid, ...control }) => (
          <PasswordField
            name="again"
            required
            autoComplete="new-password"
            isInvalid={isInvalid}
            className="w-full"
            {...control}
          />
        )}
      </FormField>
      <div className="flex items-center gap-3">
        <Button type="submit" kind="primary" isBusy={isBusy}>
          {isBusy ? "Saving" : "Save and continue"}
        </Button>
        {errors.form ? (
          <p role="alert" className="text-header font-normal text-flag">
            {errors.form}
          </p>
        ) : null}
      </div>
    </form>
  );
}
