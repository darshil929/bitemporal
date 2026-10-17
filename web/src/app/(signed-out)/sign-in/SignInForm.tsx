"use client";

import { Clock, Info, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/controls/Button";
import { FormField } from "@/components/controls/FormField";
import { PasswordField } from "@/components/controls/PasswordField";
import { TextField } from "@/components/controls/TextField";
import { Banner } from "@/components/layout/Banner";
import { apiClient } from "@/lib/api-client";

import { type Notice, refusalNotice } from "./notices";

const GLYPHS = { clock: Clock, info: Info, alert: TriangleAlert } as const;

type SignInFormProps = Readonly<{
  /** Why the previous session ended, read on the server. */
  sessionNotice?: Notice;
  /** The address to open once signed in, already held to this site. */
  next: string;
}>;

export function SignInForm({ sessionNotice, next }: SignInFormProps) {
  const router = useRouter();
  const [notice, setNotice] = useState(sessionNotice);
  const [error, setError] = useState<string>();
  const [isBusy, setBusy] = useState(false);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    const { error: refused, response } = await apiClient.POST("/auth/sign-in", {
      body: {
        username: String(form.get("username")),
        password: String(form.get("password")),
      },
    });
    if (response.ok) {
      router.replace(next);
      router.refresh();
      return;
    }
    setBusy(false);
    const detail = refused?.detail;
    const refusal =
      detail && "reason" in detail ? refusalNotice(detail) : undefined;
    setNotice(refusal);
    setError(
      refusal
        ? undefined
        : response.status === 401
          ? "The username or password is not right"
          : "Sign-in is unavailable. Try again.",
    );
  }

  return (
    <form
      onSubmit={signIn}
      className="flex w-[400px] flex-col gap-4 rounded-sm border border-border bg-surface-raised p-6"
    >
      <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-text">
        Sign in
      </h1>
      {notice ? (
        <Banner tone={notice.tone} icon={GLYPHS[notice.glyph]}>
          {notice.text}
        </Banner>
      ) : null}
      <FormField label="Username">
        {({ isInvalid, ...control }) => (
          <TextField
            name="username"
            required
            autoComplete="username"
            isInvalid={isInvalid}
            className="w-full font-mono"
            {...control}
          />
        )}
      </FormField>
      <FormField label="Password">
        {({ isInvalid, ...control }) => (
          <PasswordField
            name="password"
            required
            autoComplete="current-password"
            isInvalid={isInvalid}
            className="w-full"
            {...control}
          />
        )}
      </FormField>
      {error ? (
        <p
          role="alert"
          className="flex items-start gap-[5px] text-header leading-[1.4] font-normal text-flag"
        >
          <TriangleAlert aria-hidden="true" className="mt-px size-3 shrink-0" />
          {error}
        </p>
      ) : null}
      <div>
        <Button type="submit" kind="primary" isBusy={isBusy}>
          {isBusy ? "Signing in" : "Sign in"}
        </Button>
      </div>
      <p className="text-header leading-normal font-normal text-text-subtle">
        Accounts are created by an administrator, who also resets a forgotten
        password.
      </p>
      {notice?.isTimed ? (
        <p className="text-header leading-normal font-normal text-text-subtle">
          Times in India time
        </p>
      ) : null}
    </form>
  );
}
