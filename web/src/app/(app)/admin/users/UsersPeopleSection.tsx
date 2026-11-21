"use client";

import { Plus, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useId, useState } from "react";

import { Button } from "@/components/controls/Button";
import {
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
} from "@/components/controls/DropdownMenu";
import { FormField } from "@/components/controls/FormField";
import { Select } from "@/components/controls/Select";
import { TextField } from "@/components/controls/TextField";
import { Dialog, DialogActions } from "@/components/layout/Dialog";
import { PageHeader } from "@/components/layout/PageHeader";
import { apiClient } from "@/lib/api-client";
import {
  type IssuedPassword,
  type ManagedPerson,
  type PersonRole,
  ROLE_LABELS,
  validateNewPerson,
} from "@/lib/user-management";

import { PeopleTable } from "./PeopleTable";

type Errors = { displayName?: string; username?: string; general?: string };
const EMPTY = { displayName: "", username: "", role: "member" as PersonRole };
const ROLES: readonly PersonRole[] = ["member", "admin"];

function TemporaryPasswordDialog({
  issued,
  onClose,
}: Readonly<{ issued: IssuedPassword | null; onClose: () => void }>) {
  const [copied, setCopied] = useState(false);
  const close = () => (setCopied(false), onClose());
  const password = issued?.temporary_password ?? "";
  const copy = () =>
    navigator.clipboard
      .writeText(password)
      .then(() => setCopied(true))
      .catch(() => setCopied(false));

  return (
    <Dialog
      open={issued !== null}
      onOpenChange={(next) => (!next ? close() : undefined)}
      title={issued ? `${issued.person.display_name} added` : ""}
      footer={
        <DialogActions
          right={
            <Button type="button" kind="primary" onClick={close}>
              Done
            </Button>
          }
        />
      }
    >
      <p className="text-cell leading-normal text-text-muted">
        The temporary password of {issued?.person.display_name}, shown here
        once. Handed over in person, it is replaced at the first sign-in.
      </p>
      <FormField label="Temporary password" help="Expires in 24 hours.">
        {(c) => (
          <div className="flex items-center gap-2">
            <TextField
              {...c}
              readOnly
              value={password}
              className="min-w-0 flex-1 font-mono"
            />
            <Button type="button" kind="secondary" onClick={copy}>
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        )}
      </FormField>
    </Dialog>
  );
}

function AddPersonDialog({
  open,
  onOpenChange,
  onAdded,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded: (issued: IssuedPassword) => void;
}>) {
  const formId = useId();
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const reset = () => (setForm(EMPTY), setErrors({}));
  const setOpen = (next: boolean) => (
    next ? null : reset(),
    onOpenChange(next)
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    const { parsed, displayNameError, usernameError } = validateNewPerson(
      form.displayName,
      form.username,
    );
    if (!parsed)
      return setErrors({
        displayName: displayNameError,
        username: usernameError,
      });
    setErrors({});
    setBusy(true);
    const res = await apiClient
      .POST("/admin/users", { body: { ...parsed, role: form.role } })
      .catch(() => null);
    setBusy(false);
    if (res?.response.ok && res.data) return (reset(), onAdded(res.data));
    const taken =
      res?.response.status === 409 && res.error?.detail === "username_taken";
    setErrors(
      taken
        ? { username: "This username is already taken" }
        : { general: "The person could not be added. Try again." },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title="Add a person"
      canClose={!busy}
      footer={
        <DialogActions
          right={
            <>
              <Button
                type="button"
                disabled={busy}
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" form={formId} kind="primary" isBusy={busy}>
                {busy ? "Adding" : "Add person"}
              </Button>
            </>
          }
        />
      }
    >
      <form
        id={formId}
        onSubmit={submit}
        noValidate
        className="flex flex-col gap-3.5"
      >
        <FormField label="Display name" error={errors.displayName}>
          {(c) => (
            <TextField
              {...c}
              autoComplete="name"
              value={form.displayName}
              onChange={(e) =>
                setForm({ ...form, displayName: e.target.value })
              }
              className="w-full"
            />
          )}
        </FormField>
        <FormField label="Username" error={errors.username}>
          {(c) => (
            <TextField
              {...c}
              autoComplete="username"
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              className="w-full font-mono"
            />
          )}
        </FormField>
        <FormField label="Role">
          {({ id }) => (
            <Select id={id} value={ROLE_LABELS[form.role]} className="w-full">
              <DropdownMenuRadioGroup
                value={form.role}
                onValueChange={(v) =>
                  setForm({ ...form, role: v as PersonRole })
                }
              >
                {ROLES.map((r) => (
                  <DropdownMenuRadioItem key={r} value={r}>
                    {ROLE_LABELS[r]}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </Select>
          )}
        </FormField>
        <p className="text-header leading-normal font-normal text-text-subtle">
          A temporary password is set and shown once when the person is added.
          It expires after 24 hours and is replaced at the first sign-in.
        </p>
        {errors.general ? (
          <p
            role="alert"
            className="flex items-start gap-1.5 text-header leading-[1.4] font-normal text-flag"
          >
            <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            {errors.general}
          </p>
        ) : null}
      </form>
    </Dialog>
  );
}

// Users page header, people table, and dialogs for adding an account.
export function UsersPeopleSection({
  people,
  currentUserId,
}: Readonly<{ people: readonly ManagedPerson[]; currentUserId: number }>) {
  const router = useRouter();
  const [addOpen, setAddOpen] = useState(false);
  const [issued, setIssued] = useState<IssuedPassword | null>(null);

  return (
    <>
      <PageHeader
        title="Users"
        trailing={
          <Button type="button" kind="primary" onClick={() => setAddOpen(true)}>
            <Plus aria-hidden />
            Add person
          </Button>
        }
      />
      <PeopleTable people={people} currentUserId={currentUserId} />
      <AddPersonDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onAdded={(res) => (setAddOpen(false), setIssued(res), router.refresh())}
      />
      <TemporaryPasswordDialog
        issued={issued}
        onClose={() => setIssued(null)}
      />
    </>
  );
}
