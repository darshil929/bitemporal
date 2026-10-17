"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/controls/Button";
import { FormField } from "@/components/controls/FormField";
import { PasswordField } from "@/components/controls/PasswordField";
import { TextField } from "@/components/controls/TextField";
import { apiClient } from "@/lib/api-client";
import { PASSWORD_PROBLEMS, PASSWORDS_DIFFER } from "@/lib/password-rule";

type Errors = Readonly<{ password?: string; again?: string; form?: string }>;

// The installation's first account, which loads the history, starts syncs and adds people; creating
// it signs its holder in.
export function FirstAdminForm() {
  const router = useRouter();
  const [errors, setErrors] = useState<Errors>({});
  const [isBusy, setBusy] = useState(false);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password"));
    if (password !== String(form.get("again"))) {
      setErrors({ again: PASSWORDS_DIFFER });
      return;
    }
    setErrors({});
    setBusy(true);
    const { error, response } = await apiClient.POST("/setup/admin", {
      body: {
        display_name: String(form.get("display_name")),
        username: String(form.get("username")),
        password,
      },
    });
    // An admin created, here or meanwhile elsewhere, leaves nothing to set up.
    if (response.ok || response.status === 409) {
      router.replace("/");
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
        : { form: "The admin could not be created. Try again." },
    );
  }

  return (
    <form
      onSubmit={create}
      className="flex w-[520px] flex-col gap-4 rounded-sm border border-border bg-surface-raised p-6"
    >
      <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-text">
        Create the first admin
      </h1>
      <p className="text-cell leading-normal text-text-muted">
        The first account runs the installation: it loads the history, starts
        syncs and adds people. Nobody else can register.
      </p>
      <FormField label="Display name">
        {({ isInvalid, ...control }) => (
          <TextField
            name="display_name"
            required
            maxLength={80}
            isInvalid={isInvalid}
            className="w-full"
            {...control}
          />
        )}
      </FormField>
      <FormField label="Username">
        {({ isInvalid, ...control }) => (
          <TextField
            name="username"
            required
            minLength={3}
            maxLength={64}
            autoComplete="username"
            isInvalid={isInvalid}
            className="w-full font-mono"
            {...control}
          />
        )}
      </FormField>
      <FormField
        label="Password"
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
      <FormField label="Password again" error={errors.again}>
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
          {isBusy ? "Creating admin" : "Create admin and continue"}
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
