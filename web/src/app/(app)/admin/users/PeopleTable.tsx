import type { ReactNode } from "react";

import { NoteChip } from "@/components/status/NoteChip";
import { StatusPill } from "@/components/status/StatusPill";
import { type DataTableColumn, DataTable } from "@/components/tables/DataTable";
import { formatDateTime } from "@/lib/format";
import { type ManagedPerson, ROLE_LABELS } from "@/lib/user-management";

function dim(content: ReactNode, disabled: boolean): ReactNode {
  return disabled ? (
    <span className="text-text-subtle">{content}</span>
  ) : (
    content
  );
}

function statusCell(p: ManagedPerson): ReactNode {
  if (p.disabled_at !== null) return <StatusPill>Disabled</StatusPill>;
  if (p.must_change_password) return <NoteChip>Must change password</NoteChip>;
  return "Active";
}

// Every account on the installation, newest first, disabled accounts dimmed in text-subtle.
export function PeopleTable({
  people,
  currentUserId,
  renderActions,
}: Readonly<{
  people: readonly ManagedPerson[];
  currentUserId: number;
  renderActions?: (person: ManagedPerson) => ReactNode;
}>) {
  const columns: DataTableColumn<ManagedPerson>[] = [
    {
      key: "name",
      header: "Display name",
      cell: (p) => (
        <span className="inline-flex items-center gap-2 font-medium">
          {dim(p.display_name, p.disabled_at !== null)}
          {p.id === currentUserId ? <NoteChip>This account</NoteChip> : null}
        </span>
      ),
    },
    {
      key: "username",
      header: "Username",
      cell: (p) => (
        <span className="font-mono text-header font-normal">
          {dim(p.username, p.disabled_at !== null)}
        </span>
      ),
    },
    {
      key: "role",
      header: "Role",
      width: "96px",
      cell: (p) => dim(ROLE_LABELS[p.role], p.disabled_at !== null),
    },
    { key: "status", header: "Status", width: "190px", cell: statusCell },
    {
      key: "last",
      header: "Last signed in",
      width: "160px",
      cell: (p) =>
        p.last_signed_in ? (
          dim(formatDateTime(p.last_signed_in), p.disabled_at !== null)
        ) : (
          <span className="text-text-subtle">Never</span>
        ),
    },
    {
      key: "added",
      header: "Added",
      width: "120px",
      cell: (p) =>
        dim(
          formatDateTime(p.created_at).split(", ")[0],
          p.disabled_at !== null,
        ),
    },
    ...(renderActions
      ? [
          {
            key: "actions",
            header: "",
            width: "48px",
            align: "end" as const,
            cell: renderActions,
          },
        ]
      : []),
  ];
  const noun = people.length === 1 ? "person" : "people";
  return (
    <DataTable
      caption="People with accounts on this installation"
      columns={columns}
      rows={people}
      rowKey={(p) => String(p.id)}
      footer={`${people.length} ${noun}. Newest first. Times in India time`}
    />
  );
}
