import { StatusPill } from "@/components/status/StatusPill";
import { STATE_GLYPHS } from "@/components/status/data-state-glyphs";
import type { components } from "@/lib/api";
import { cn } from "cn";
import {
  type DataStatus,
  figureRows,
  headline,
  isFlagged,
  STATE_WORDS,
} from "@/lib/data-status";
import { formatCount } from "@/lib/format";

type RunHistory = components["schemas"]["RunHistoryResponse"];

// The day every page shows and what stands behind it: each venue's latest day, a sync running,
// the days never asked for.
export function FiguresCard({
  status,
  history,
}: Readonly<{ status: DataStatus; history: RunHistory }>) {
  return (
    <section className="flex flex-col gap-3.5 rounded-sm border border-border bg-surface-raised p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-title tracking-[-0.01em] text-text">
          {headline(status)}
        </h2>
        <StatusPill
          tone={isFlagged(status.state) ? "flag" : "neutral"}
          icon={STATE_GLYPHS[status.state]}
        >
          {STATE_WORDS[status.state]}
        </StatusPill>
      </div>
      {status.published_day ? (
        <p className="text-cell leading-normal text-text-muted">
          The day every page shows: the published day of the daily features,{" "}
          <span className="tabular-nums">
            {formatCount(history.published_instruments)}
          </span>{" "}
          instruments. A failed check never replaces it.
        </p>
      ) : null}
      <dl>
        {figureRows(status, history.days_never_asked).map((row) => (
          <div
            key={row.label}
            className="grid grid-cols-[180px_minmax(0,1fr)] items-baseline gap-3 border-t border-border py-[7px]"
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
    </section>
  );
}
