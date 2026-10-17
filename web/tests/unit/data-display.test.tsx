import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { Card } from "@/components/tables/Card";
import { type DataTableColumn, DataTable } from "@/components/tables/DataTable";
import { KeyFigureList } from "@/components/tables/KeyFigureList";
import { BpsCell } from "@/components/values/BpsCell";
import { PriceCell } from "@/components/values/PriceCell";

afterEach(cleanup);

type Action = Readonly<{
  date: string;
  kind: string;
  terms: string;
  factor: string;
}>;

const ACTIONS: readonly Action[] = [
  { date: "26 Aug 2025", kind: "Bonus", terms: "1 for 1", factor: "0.5" },
  { date: "14 Oct 2025", kind: "Unhandled", terms: "Spin Off", factor: "—" },
];

const COLUMNS: readonly DataTableColumn<Action>[] = [
  { key: "date", header: "Ex-date", width: "112px", cell: (r) => r.date },
  { key: "kind", header: "Action", cell: (r) => r.kind },
  { key: "terms", header: "Terms", isCriterion: true, cell: (r) => r.terms },
  {
    key: "factor",
    header: "Factor",
    align: "end",
    isSorted: true,
    cell: (r) => r.factor,
  },
];

const NO_BAR = "No bar for this day";

function Actions(props: Readonly<{ footer?: string; rowHeight?: 32 | 40 }>) {
  return (
    <DataTable
      caption="Corporate actions of HDFC Bank"
      columns={COLUMNS}
      rows={ACTIONS}
      rowKey={(r) => r.date}
      isFlagged={(r) => r.kind === "Unhandled"}
      {...props}
    />
  );
}

test("a card shows its title, the caption under it and what sits beside it", () => {
  render(
    <Card
      title="Listings"
      caption="From the first recorded day."
      aside={<a href="#actions">All 26 actions</a>}
    >
      <p>Rows</p>
    </Card>,
  );

  expect(screen.getByRole("heading", { name: "Listings" })).toBeDefined();
  expect(screen.getByText("From the first recorded day.")).toBeDefined();
  expect(screen.getByRole("link", { name: "All 26 actions" })).toBeDefined();
  expect(screen.getByText("Rows")).toBeDefined();
});

test("a data table lays each row's cells under their headers, figures at the column's end", () => {
  render(<Actions rowHeight={32} />);

  const table = screen.getByRole("table", {
    name: "Corporate actions of HDFC Bank",
  });
  const headers = within(table).getAllByRole("columnheader");
  expect(headers.map((header) => header.textContent)).toEqual([
    "Ex-date",
    "Action",
    "Terms (criterion)",
    "Factor",
  ]);
  const cells = within(within(table).getAllByRole("row")[1]).getAllByRole(
    "cell",
  );
  expect(cells.map((cell) => cell.textContent)).toEqual([
    "26 Aug 2025",
    "Bonus",
    "1 for 1",
    "0.5",
  ]);
  expect(cells[3].classList).toContain("text-right");
  expect(cells[0].classList).toContain("h-8");
  expect(cells[0].classList).toContain("tabular-nums");
});

test("the sorted column is announced highest first, a flagged row shaded, the footer beneath", () => {
  render(<Actions footer="2 actions" />);

  const sorted = screen.getByRole("columnheader", { name: "Factor" });
  expect(sorted.getAttribute("aria-sort")).toBe("descending");
  expect(sorted.classList).toContain("text-text");
  expect(
    screen
      .getByRole("columnheader", { name: "Action" })
      .hasAttribute("aria-sort"),
  ).toBe(false);
  const [, bonus, unhandled] = screen.getAllByRole("row");
  expect(unhandled.classList).toContain("bg-flag-surface");
  expect(bonus.classList).not.toContain("bg-flag-surface");
  expect(bonus.firstElementChild?.classList).toContain("h-10");
  expect(screen.getByText("2 actions")).toBeDefined();
});

test("key figures read as label and value rows under the venue and day, sources beneath", () => {
  render(
    <KeyFigureList
      caption="NSE, 15 Oct 2026"
      figures={[
        { label: "Open", value: <PriceCell value={715} nullReason={NO_BAR} /> },
        {
          label: "Venue spread",
          value: (
            <BpsCell value={23.3613} isDiverging={false} nullReason={NO_BAR} />
          ),
        },
      ]}
      sources="From the NSE bhavcopy."
    />,
  );

  expect(screen.getByRole("heading", { name: "Key figures" })).toBeDefined();
  expect(screen.getByText("NSE, 15 Oct 2026")).toBeDefined();
  const labels = screen.getAllByRole("term").map((term) => term.textContent);
  expect(labels).toEqual(["Open", "Venue spread"]);
  const values = screen
    .getAllByRole("definition")
    .map((value) => value.textContent);
  expect(values).toEqual(["₹715.00", "23bps"]);
  expect(screen.getByText("From the NSE bhavcopy.")).toBeDefined();
});
