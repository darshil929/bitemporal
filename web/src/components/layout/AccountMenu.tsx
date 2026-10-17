"use client";

import { ChevronDown, TriangleAlert, User } from "lucide-react";
import { useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/controls/DropdownMenu";
import { StatusPill } from "@/components/status/StatusPill";
import type { components } from "@/lib/api";
import { apiClient } from "@/lib/api-client";
import { SIGNED_OUT_ADDRESS } from "@/lib/return-address";

type Person = Pick<
  components["schemas"]["SessionResponse"],
  "display_name" | "username" | "role"
>;

const ROLES = { admin: "Admin", member: "Member" } as const;

// The person signed in, and signing out. Signing out ends this browser's session alone and opens
// sign-in by a whole page load, so nothing read for the person stays in the browser.
export function AccountMenu({ person }: Readonly<{ person: Person }>) {
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");

  async function signOut(event: Event) {
    // The menu stays open while the request runs, and says so if it fails.
    event.preventDefault();
    if (state === "busy") {
      return;
    }
    setState("busy");
    const signedOut = await apiClient
      .POST("/auth/sign-out")
      .then(({ response }) => response.ok)
      .catch(() => false);
    if (signedOut) {
      window.location.assign(SIGNED_OUT_ADDRESS);
      return;
    }
    setState("failed");
  }

  return (
    <DropdownMenu
      onOpenChange={() =>
        setState((current) => (current === "failed" ? "idle" : current))
      }
    >
      <DropdownMenuTrigger className="inline-flex h-control items-center gap-2 rounded-sm border border-border bg-surface-raised pr-2 pl-1 text-cell font-medium whitespace-nowrap text-text outline-none focus-visible:border-accent data-[state=open]:border-accent">
        <span className="inline-flex size-6 items-center justify-center rounded-full border border-border bg-surface-sunken">
          <User aria-hidden="true" className="size-[13px] text-text-muted" />
        </span>
        {person.display_name}
        <ChevronDown
          aria-hidden="true"
          className="size-[13px] text-text-subtle"
        />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[248px] min-w-0">
        <div className="flex items-start justify-between gap-2 px-2 pt-0.5 pb-2.5">
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate text-cell font-semibold text-text">
              {person.display_name}
            </span>
            <span className="truncate font-mono text-caption text-text-subtle">
              {person.username}
            </span>
          </div>
          <StatusPill>{ROLES[person.role]}</StatusPill>
        </div>
        <DropdownMenuSeparator className="mt-0" />
        <DropdownMenuItem onSelect={signOut}>
          {state === "busy" ? "Signing out" : "Sign out"}
        </DropdownMenuItem>
        {state === "failed" ? (
          <p
            role="alert"
            className="flex items-start gap-[5px] px-2 pt-1 text-caption leading-[1.4] text-flag"
          >
            <TriangleAlert
              aria-hidden="true"
              className="mt-px size-3 shrink-0"
            />
            Sign-out is unavailable. Try again.
          </p>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
