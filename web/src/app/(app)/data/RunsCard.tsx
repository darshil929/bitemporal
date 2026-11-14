import { Check, TriangleAlert, X } from "lucide-react";

import { StatusPill } from "@/components/status/StatusPill";
import { Card } from "@/components/tables/Card";
import { type DataTableColumn, DataTable } from "@/components/tables/DataTable";
import { formatDateTime, formatDayRange, formatSpan } from "@/lib/format";
import {
  checksLine,
  flowName,
  OUTCOME_WORDS,
  type RecordedRun,
  runDetail,
  startedBy,
} from "@/lib/run-history";

const OUTCOME_GLYPHS = {
  succeeded: Check,
  failed: TriangleAlert,
  cancelled: X,
} as const;

const COLUMNS: readonly DataTableColumn<RecordedRun>[] = [
  {
    key: "started",
    header: "Started",
    width: "160px",
    cell: (run) => formatDateTime(run.started_at),
  },
  { key: "flow", header: "Flow", width: "96px", cell: flowName },
  {
    key: "days",
    header: "Days",
    width: "190px",
    cell: (run) => formatDayRange(run.first_day, run.last_day),
  },
  {
    key: "duration",
    header: "Duration",
    width: "116px",
    align: "end",
    cell: (run) => formatSpan(run.duration_seconds),
  },
  {
    key: "outcome",
    header: "Outcome",
    width: "124px",
    cell: (run) => (
      <StatusPill
        tone={run.outcome === "failed" ? "flag" : "neutral"}
        icon={OUTCOME_GLYPHS[run.outcome]}
      >
        {OUTCOME_WORDS[run.outcome]}
      </StatusPill>
    ),
  },
  { key: "checks", header: "Checks", width: "220px", cell: checksLine },
  {
    key: "detail",
    header: "Detail",
    cell: (run) => (
      <span
        className={run.outcome === "failed" ? "text-flag" : "text-text-muted"}
      >
        {runDetail(run)}
      </span>
    ),
  },
  { key: "by", header: "Started by", width: "130px", cell: startedBy },
];

// The newest runs of either flow, newest first, a failed run flagged.
export function RunsCard({ runs }: Readonly<{ runs: readonly RecordedRun[] }>) {
  return (
    <Card title="Runs">
      <DataTable
        caption="The newest runs of the flows"
        columns={COLUMNS}
        rows={runs}
        rowKey={(run) => run.run_id}
        isFlagged={(run) => run.outcome === "failed"}
        footer={
          runs.length === 0
            ? "No run recorded"
            : `The last ten runs: ${runs.length} recorded. Times in India time`
        }
      />
    </Card>
  );
}
