"use client";

import { Check, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/controls/Button";
import { FormField } from "@/components/controls/FormField";
import { TextField } from "@/components/controls/TextField";
import { apiClient } from "@/lib/api-client";
import {
  type SessionLimits,
  validateSessionLimits,
} from "@/lib/user-management";

type SaveState = "idle" | "busy" | "saved" | "failed";

// Installation-wide session idle and maximum duration settings edited by an admin.
export function SessionLimitsCard({
  limits,
}: Readonly<{ limits: SessionLimits }>) {
  const router = useRouter();
  const [idleText, setIdleText] = useState(String(limits.session_idle_minutes));
  const [maxText, setMaxText] = useState(String(limits.session_max_hours));
  const [errors, setErrors] = useState<{ idle?: string; max?: string }>({});
  const [status, setStatus] = useState<SaveState>("idle");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const { parsed, idleError, maxError } = validateSessionLimits(
      idleText,
      maxText,
    );
    if (!parsed) {
      setErrors({ idle: idleError, max: maxError });
      return setStatus("idle");
    }
    setErrors({});
    setStatus("busy");
    const body = {
      session_idle_minutes: parsed.idle,
      session_max_hours: parsed.max,
    };
    const ok = await apiClient
      .PATCH("/admin/settings", { body })
      .then(({ response }) => response.ok)
      .catch(() => false);
    if (!ok) return setStatus("failed");
    setStatus("saved");
    router.refresh();
  }

  const fields = [
    ["Idle limit", "minutes", idleText, errors.idle, setIdleText],
    ["Maximum", "hours", maxText, errors.max, setMaxText],
  ] as const;

  return (
    <section className="flex flex-col gap-3.5 rounded-sm border border-border bg-surface-raised p-5">
      <h2 className="text-heading text-text">Session limits</h2>
      <form onSubmit={submit} noValidate className="flex flex-col gap-3.5">
        <div className="flex flex-wrap items-start gap-4">
          {fields.map(([label, unit, value, error, set]) => (
            <FormField key={label} label={label} error={error}>
              {(c) => (
                <TextField
                  {...c}
                  inputMode="numeric"
                  unit={unit}
                  value={value}
                  onChange={(e) => {
                    set(e.target.value);
                    setStatus("idle");
                  }}
                  className="w-40"
                />
              )}
            </FormField>
          ))}
        </div>
        <div className="flex items-center gap-2.5">
          <Button type="submit" kind="secondary" isBusy={status === "busy"}>
            {status === "busy" ? "Saving" : "Save"}
          </Button>
          {status === "saved" ? (
            <span className="inline-flex items-center gap-1 text-header font-normal text-text-muted">
              <Check aria-hidden strokeWidth={2.5} className="size-3" />
              Saved
            </span>
          ) : null}
        </div>
        {status === "failed" ? (
          <p
            role="alert"
            className="flex items-start gap-1.5 text-header leading-[1.4] font-normal text-flag"
          >
            <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            The session limits could not be saved. Try again.
          </p>
        ) : null}
      </form>
      <p className="text-header leading-normal font-normal text-text-subtle">
        Defaults: 120 minutes without activity, 12 hours at most. A person past
        either signs in again.
      </p>
    </section>
  );
}
