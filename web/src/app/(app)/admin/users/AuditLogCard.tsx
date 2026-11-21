import { EmptyState } from "@/components/layout/EmptyState";
import { type DataTableColumn, DataTable } from "@/components/tables/DataTable";
import { formatDateTime } from "@/lib/format";
import {
  auditActionLabel,
  auditDetail,
  type AuditEntry,
} from "@/lib/user-management";

const COLUMNS: readonly DataTableColumn<AuditEntry>[] = [
  {
    key: "when",
    header: "When",
    width: "160px",
    cell: (e) => formatDateTime(e.occurred_at),
  },
  { key: "who", header: "Who", width: "160px", cell: (e) => e.actor_name },
  { key: "action", header: "Action", cell: (e) => auditActionLabel(e.action) },
  { key: "detail", header: "Detail", cell: auditDetail },
];

// The recent changes admins made, newest first.
export function AuditLogCard({
  entries,
}: Readonly<{ entries: readonly AuditEntry[] }>) {
  return (
    <section className="flex flex-col gap-3.5 rounded-sm border border-border bg-surface-raised p-5">
      <h2 className="text-heading text-text">Recent admin actions</h2>
      {entries.length === 0 ? (
        <EmptyState
          title="No actions yet"
          text="Every change an admin makes is recorded here."
        />
      ) : (
        <DataTable
          caption="Recent admin actions"
          columns={COLUMNS}
          rows={entries}
          rowKey={(e) =>
            `${e.occurred_at}:${e.actor_id}:${e.action}:${e.subject_id ?? ""}`
          }
        />
      )}
      <p className="text-header leading-normal font-normal text-text-subtle">
        Newest first. Times in India time.
      </p>
    </section>
  );
}
