import type { ReactNode } from "react";

import { NoteChip } from "@/components/status/NoteChip";
import { StatusPill } from "@/components/status/StatusPill";
import { type DataTableColumn, DataTable } from "@/components/tables/DataTable";
import { formatCount } from "@/lib/format";
import {
  checksLine,
  DAILY_SOURCES,
  dailyCountRows,
  otherSourceRows,
  OUTCOME_WORDS,
  type RecordedRun,
  runDetail,
  runHeading,
  runSummary,
  sourceLabel,
} from "@/lib/run-history";

import { OUTCOME_GLYPHS } from "./RunsCard";

type DailyRow = ReturnType<typeof dailyCountRows>[number];
type OtherRow = ReturnType<typeof otherSourceRows>[number];

const DASH = <span className="text-text-subtle">—</span>;
const CARD_CLASS =
  "flex flex-col gap-3.5 rounded-sm border border-border bg-surface-raised p-5";

function countCell(value: number | null, isFailure: boolean): ReactNode {
  if (value === null) return DASH;
  return isFailure && value > 0 ? (
    <span className="font-semibold text-flag">{formatCount(value)}</span>
  ) : (
    formatCount(value)
  );
}

const DAILY_COLUMNS: readonly DataTableColumn<DailyRow>[] = [
  { key: "count", header: "Daily files", cell: (r) => r.label },
  ...DAILY_SOURCES.map<DataTableColumn<DailyRow>>(([key, header]) => ({
    key,
    header,
    width: "104px",
    align: "end",
    cell: (r) => countCell(r.values[key], r.isFailure),
  })),
];

const OTHER_COLUMNS: readonly DataTableColumn<OtherRow>[] = [
  {
    key: "source",
    header: "Corporate actions and lists",
    cell: (r) => r.source,
  },
  {
    key: "read",
    header: "Read",
    width: "120px",
    align: "end",
    cell: (r) => r.read ?? DASH,
  },
  {
    key: "failed",
    header: "Failed",
    width: "104px",
    align: "end",
    cell: (r) => countCell(r.failed, true),
  },
];

function CheckLine(
  p: Readonly<{ failed: boolean; name: string; rows: number | null }>,
) {
  return (
    <div
      className={`flex flex-wrap items-center gap-2 text-header font-normal ${p.failed ? "text-flag" : "text-text-muted"}`}
    >
      <NoteChip tone={p.failed ? "flag" : "neutral"}>
        {p.failed ? "Failed" : "Warned"}
      </NoteChip>
      <span className="font-mono">{p.name}</span>
      {p.rows !== null ? (
        <span className="tabular-nums">
          {formatCount(p.rows)} {p.rows === 1 ? "row" : "rows"}
        </span>
      ) : null}
    </div>
  );
}

// The newest recorded run's report: daily-file counts, corporate action and list reads, failures,
// and check outcomes.
export function LastSyncCard({ run }: Readonly<{ run: RecordedRun | null }>) {
  if (run === null) {
    return (
      <section className={CARD_CLASS}>
        <h2 className="text-heading text-text">{runHeading(null)}</h2>
        <p className="text-cell leading-normal text-text-muted">
          No sync recorded
        </p>
      </section>
    );
  }
  const otherRows = otherSourceRows(run);
  const failureSummary = run.outcome === "failed" ? runDetail(run) : "";
  return (
    <section className={CARD_CLASS}>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-heading text-text">{runHeading(run)}</h2>
        <StatusPill
          tone={run.outcome === "failed" ? "flag" : "neutral"}
          icon={OUTCOME_GLYPHS[run.outcome]}
        >
          {OUTCOME_WORDS[run.outcome]}
        </StatusPill>
      </div>
      <p className="text-cell leading-normal text-text-muted tabular-nums">
        {runSummary(run)}
      </p>
      <div className="flex flex-col gap-3">
        <DataTable
          caption="Daily file counts from the latest run"
          columns={DAILY_COLUMNS}
          rows={dailyCountRows(run)}
          rowKey={(r) => r.key}
          rowHeight={32}
        />
        {otherRows.length > 0 ? (
          <DataTable
            caption="Corporate action and list reads from the latest run"
            columns={OTHER_COLUMNS}
            rows={otherRows}
            rowKey={(r) => r.key}
            rowHeight={32}
          />
        ) : null}
      </div>
      {failureSummary || run.failures.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          {failureSummary ? (
            <p className="text-cell leading-normal text-flag">
              {failureSummary}
            </p>
          ) : null}
          {run.failures.map((f) => (
            <div
              key={`${f.source}:${f.key}:${f.detail}`}
              className="flex flex-wrap items-center gap-2 text-header font-normal text-flag"
            >
              <NoteChip tone="flag">Failed</NoteChip>
              <span>{sourceLabel(f.source)}</span>
              <span className="font-mono">{f.key}</span>
              <span>{f.detail}</span>
            </div>
          ))}
        </div>
      ) : null}
      <div className="flex flex-col gap-1.5">
        <div className="text-cell text-text">
          Checks <span className="tabular-nums">{checksLine(run)}</span>
        </div>
        {run.warned_checks.map((c) => (
          <CheckLine key={`w:${c.name}`} failed={false} {...c} />
        ))}
        {run.failed_checks.map((c) => (
          <CheckLine key={`f:${c.name}`} failed {...c} />
        ))}
      </div>
    </section>
  );
}
