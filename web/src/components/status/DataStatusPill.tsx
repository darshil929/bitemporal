"use client";

import {
  Check,
  ChevronDown,
  Clock,
  Info,
  type LucideIcon,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";

import { cn } from "cn";

import { StatusPill } from "@/components/status/StatusPill";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { apiQueries } from "@/lib/api-client";
import {
  type DataState,
  type DataStatus,
  factRows,
  headline,
  isFlagged,
  pillText,
  STATE_WORDS,
} from "@/lib/data-status";

const GLYPHS: Record<DataState, LucideIcon> = {
  fresh: Check,
  updating: Clock,
  stale: TriangleAlert,
  failed: TriangleAlert,
  unknown: Info,
};

// Read again every minute, and every ten seconds while a sync waits or runs.
const READ_EVERY_MS = 60_000;
const READ_WHILE_UPDATING_MS = 10_000;

// How current the figures are, in a word and the day the pages show, with the facts behind it.
export function DataStatusPill({ isAdmin }: Readonly<{ isAdmin: boolean }>) {
  const { data } = apiQueries.useQuery("get", "/data/status", undefined, {
    refetchInterval: (query) =>
      query.state.data?.running ? READ_WHILE_UPDATING_MS : READ_EVERY_MS,
  });
  const neverAsked = apiQueries.useQuery("get", "/data/runs", undefined, {
    enabled: isAdmin && (data?.days_never_asked ?? 0) > 0,
  });
  if (!data) {
    return null;
  }
  const Glyph = GLYPHS[data.state];
  const flagged = isFlagged(data.state);
  return (
    <Popover>
      <PopoverTrigger
        className={cn(
          "inline-flex h-control items-center gap-1.5 rounded-sm border pr-2 pl-2.5 text-cell whitespace-nowrap outline-none focus-visible:border-accent data-[state=open]:border-accent",
          flagged
            ? "border-flag-border bg-flag-surface text-flag"
            : "border-border bg-surface-raised text-text-muted",
        )}
      >
        <Glyph aria-hidden="true" strokeWidth={2.2} className="size-3.5" />
        <span className="tabular-nums">
          <span
            className={cn("font-medium", flagged ? "text-flag" : "text-text")}
          >
            {STATE_WORDS[data.state]}
          </span>
          {pillText(data).slice(STATE_WORDS[data.state].length)}
        </span>
        <ChevronDown
          aria-hidden="true"
          className="size-[13px] text-text-subtle"
        />
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="flex w-[440px] flex-col gap-2.5 rounded-sm border-border-strong bg-surface-raised p-3 text-text shadow-none"
      >
        <DataStatusFacts
          status={data}
          isAdmin={isAdmin}
          stretches={neverAsked.data?.days_never_asked ?? []}
        />
      </PopoverContent>
    </Popover>
  );
}

export function DataStatusFacts({
  status,
  isAdmin,
  stretches,
}: Readonly<{
  status: DataStatus;
  isAdmin: boolean;
  stretches: Parameters<typeof factRows>[2];
}>) {
  const Glyph = GLYPHS[status.state];
  const link = status.state === "failed" ? "Open the run" : "Open data status";
  return (
    <>
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-body font-semibold">{headline(status)}</h3>
        <StatusPill
          tone={isFlagged(status.state) ? "flag" : "neutral"}
          icon={Glyph}
        >
          {STATE_WORDS[status.state]}
        </StatusPill>
      </div>
      <dl>
        {factRows(status, isAdmin, stretches).map((row) => (
          <div
            key={row.label}
            className="grid grid-cols-[150px_minmax(0,1fr)] items-baseline gap-3 border-t border-border py-[7px]"
          >
            <dt className="text-header text-text-muted">{row.label}</dt>
            <dd
              className={cn(
                "text-cell leading-[1.4] tabular-nums",
                row.flagged ? "text-flag" : "text-text",
              )}
            >
              {row.value}
              {row.detail ? (
                <div
                  className={cn(
                    "text-header",
                    row.flagged ? "text-flag" : "text-text-muted",
                  )}
                >
                  {row.detail}
                </div>
              ) : null}
            </dd>
          </div>
        ))}
      </dl>
      <div className="flex items-center justify-between gap-3 text-caption text-text-subtle">
        <span>Times in India time</span>
        {isAdmin && status.state !== "unknown" ? (
          <Link href="/data" className="text-header text-accent">
            {link}
          </Link>
        ) : null}
      </div>
    </>
  );
}
