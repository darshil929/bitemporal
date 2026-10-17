import { ArrowDown, Filter } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "cn";

export type DataTableColumn<Row> = Readonly<{
  key: string;
  header: string;
  /** A fixed width, such as "112px"; columns without one share what is left. */
  width?: string;
  /** Figures align at the end of their column. */
  align?: "start" | "end";
  /** The column the rows are ordered by, highest first. */
  isSorted?: boolean;
  /** A column a criterion of the view filters on. */
  isCriterion?: boolean;
  cell: (row: Row) => ReactNode;
}>;

const ROW_HEIGHTS = { 32: "h-8", 40: "h-10", 48: "h-12" } as const;

type DataTableProps<Row> = Readonly<{
  /** What the rows are, read out as the table's caption. */
  caption: string;
  columns: readonly DataTableColumn<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  /** A row carrying something to look at, shaded with the flag. */
  isFlagged?: (row: Row) => boolean;
  rowHeight?: keyof typeof ROW_HEIGHTS;
  /** Under the rows, such as their count and order. */
  footer?: ReactNode;
}>;

function HeaderMarks<Row>({
  column,
}: Readonly<{ column: DataTableColumn<Row> }>) {
  return (
    <>
      {column.isCriterion ? (
        <Filter aria-hidden="true" className="size-[11px] text-text-subtle" />
      ) : null}
      {column.isSorted ? (
        <ArrowDown
          aria-hidden="true"
          strokeWidth={2.5}
          className="size-[11px]"
        />
      ) : null}
    </>
  );
}

// Rows of figures under column headers; a figure's column aligns at its end, and a column's marks
// sit on the side away from its figures.
export function DataTable<Row>({
  caption,
  columns,
  rows,
  rowKey,
  isFlagged,
  rowHeight = 40,
  footer,
}: DataTableProps<Row>) {
  return (
    <div className="overflow-hidden rounded-sm border border-border bg-surface-raised">
      <table className="w-full table-fixed border-collapse">
        <caption className="sr-only">{caption}</caption>
        <colgroup>
          {columns.map((column) => (
            <col
              key={column.key}
              style={column.width ? { width: column.width } : undefined}
            />
          ))}
        </colgroup>
        <thead className="bg-surface-sunken">
          <tr className="border-b border-border">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                aria-sort={column.isSorted ? "descending" : undefined}
                className={cn(
                  "h-8 px-cell text-header whitespace-nowrap",
                  column.isSorted ? "text-text" : "text-text-muted",
                  column.align === "end" ? "text-right" : "text-left",
                )}
              >
                <span className="inline-flex items-center gap-1">
                  {column.align === "end" ? (
                    <HeaderMarks column={column} />
                  ) : null}
                  {column.header}
                  {column.isCriterion ? (
                    <>
                      {" "}
                      <span className="sr-only">(criterion)</span>
                    </>
                  ) : null}
                  {column.align === "end" ? null : (
                    <HeaderMarks column={column} />
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const flagged = isFlagged?.(row) ?? false;
            return (
              <tr
                key={rowKey(row)}
                data-flagged={flagged || undefined}
                className={cn(
                  "border-b border-border last:border-b-0",
                  flagged && "bg-flag-surface",
                )}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      ROW_HEIGHTS[rowHeight],
                      "px-cell text-cell text-text tabular-nums",
                      column.align === "end" ? "text-right" : "text-left",
                    )}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {footer ? (
        <div className="flex items-center justify-between gap-3 border-t border-border px-cell py-2.5 text-header font-normal text-text-muted">
          {footer}
        </div>
      ) : null}
    </div>
  );
}
