import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Info } from "lucide-react";
import { afterEach, expect, test, vi } from "vitest";

import { ActionMarker } from "@/components/status/ActionMarker";
import { AlertStatus } from "@/components/status/AlertStatus";
import { DayCompleteness } from "@/components/status/DayCompleteness";
import { NoteChip } from "@/components/status/NoteChip";
import { ProvenanceChip } from "@/components/status/ProvenanceChip";
import { StalePill } from "@/components/status/StalePill";
import { StatusPill } from "@/components/status/StatusPill";
import { VenueBadge } from "@/components/status/VenueBadge";

afterEach(cleanup);

// The popover measures its trigger as a browser does; the test DOM has no resize observer.
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  },
);

function shown(container: HTMLElement): { text: string; tone?: string } {
  const element = container.firstElementChild as HTMLElement;
  return { text: element.textContent ?? "", tone: element.dataset.tone };
}

test("the primary venue's badge is marked and stronger than the other's", () => {
  const primary = render(<VenueBadge venue="NSE" isPrimary />).container;
  const other = render(<VenueBadge venue="BSE" />).container;

  expect(primary.firstElementChild?.textContent).toBe("NSEPrimary");
  expect(primary.firstElementChild?.classList).toContain(
    "border-border-strong",
  );
  expect(other.firstElementChild?.textContent).toBe("BSE");
  expect(other.firstElementChild?.classList).toContain("text-text-muted");
});

test.each([
  ["neutral", "text-text-muted"],
  ["flag", "text-flag"],
] as const)(
  "a %s status pill reads in %s with its glyph hidden",
  (tone, ink) => {
    const { container } = render(
      <StatusPill tone={tone} icon={Info}>
        Listed at BSE only
      </StatusPill>,
    );

    const pill = container.firstElementChild;
    expect(pill?.classList).toContain(ink);
    expect(pill?.querySelector("svg")?.getAttribute("aria-hidden")).toBe(
      "true",
    );
  },
);

test.each([
  [1, "30 Dec 2025, one trading day behind"],
  [3, "30 Dec 2025, 3 trading days behind"],
  [undefined, "30 Dec 2025"],
])("a stale pill %s days behind reads %s", (days, text) => {
  const { container } = render(
    <StalePill isoDate="2025-12-30" tradingDaysBehind={days} />,
  );

  expect(shown(container)).toEqual({ text, tone: "neutral" });
});

test("a complete day takes no price colour; a partial one carries the flag", () => {
  const complete = render(<DayCompleteness venue="BSE" isComplete />).container;
  const partial = render(
    <DayCompleteness venue="NSE" isComplete={false} />,
  ).container;

  expect(shown(complete)).toEqual({ text: "BSE complete", tone: "neutral" });
  expect(complete.querySelector(".text-up")).toBeNull();
  expect(shown(partial)).toEqual({ text: "NSE partial", tone: "flag" });
});

test.each([
  ["triggered", "Triggered", "flag"],
  ["watching", "Watching", "neutral"],
  ["paused", "Paused", "neutral"],
] as const)("an alert %s reads %s in the %s tone", (status, text, tone) => {
  const { container } = render(<AlertStatus status={status} />);

  expect(shown(container)).toEqual({ text, tone });
});

test.each([
  ["neutral", "Superseded"],
  ["flag", "Unhandled action in range"],
] as const)("a %s note chip reads %s", (tone, text) => {
  const { container } = render(<NoteChip tone={tone}>{text}</NoteChip>);

  expect(shown(container)).toEqual({ text, tone });
});

test.each([
  ["dividend", "D", "Dividend"],
  ["bonus", "B", "Bonus"],
  ["split", "S", "Split"],
  ["consolidation", "C", "Consolidation"],
  ["rights", "R", "Rights"],
  ["unhandled", "!", "Unhandled action"],
] as const)(
  "a %s marker reads %s and is named %s",
  (actionType, letter, label) => {
    render(<ActionMarker actionType={actionType} />);

    const marker = screen.getByRole("img", { name: label });
    expect(marker.textContent).toBe(letter);
    expect(marker.classList.contains("text-flag")).toBe(
      actionType === "unhandled",
    );
  },
);

const NSE_FIGURES = [
  {
    source_id: "nse_bhavcopy_equity",
    tier: 1,
    sebi_curation_ref: "Equity Cash Market, row 1",
  },
  {
    source_id: "nse_delivery",
    tier: 1,
    sebi_curation_ref: "Equity Cash Market, row 2",
  },
  {
    source_id: "bse_bhavcopy_equity",
    tier: 1,
    sebi_curation_ref: "Equity Cash Market, row 1",
  },
];

function details(): string[] {
  return screen
    .getAllByRole("listitem")
    .map((source) => source.textContent ?? "");
}

test("the provenance chip names its sources, their lowest tier and the day published", () => {
  render(<ProvenanceChip sources={NSE_FIGURES} isoDate="2026-10-15" />);

  expect(screen.getByRole("button").textContent).toBe(
    "NSE bhavcopy, NSE delivery file, BSE bhavcopy Tier 1 15 Oct 2026",
  );
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("the provenance detail states each source's identifier, tier and SEBI curation row", () => {
  render(<ProvenanceChip sources={NSE_FIGURES} isoDate="2026-10-15" />);
  fireEvent.click(screen.getByRole("button"));

  const detail = screen.getByRole("dialog");
  expect(screen.getByRole("heading").textContent).toBe(
    "Where these figures come from",
  );
  expect(detail.textContent).toContain("Published 15 Oct 2026");
  expect(details()).toEqual([
    "NSE bhavcopynse_bhavcopy_equityTier 1, exchange bulk file. SEBI curation: Equity Cash Market, row 1",
    "NSE delivery filense_deliveryTier 1, exchange bulk file. SEBI curation: Equity Cash Market, row 2",
    "BSE bhavcopybse_bhavcopy_equityTier 1, exchange bulk file. SEBI curation: Equity Cash Market, row 1",
  ]);
});

test("a source without a curation row reads its tier alone, and an unnamed one its identifier", () => {
  render(
    <ProvenanceChip
      sources={[
        {
          source_id: "bse_corporate_actions",
          tier: 2,
          sebi_curation_ref: null,
        },
        { source_id: "bse_results", tier: 2, sebi_curation_ref: null },
      ]}
      isoDate="2026-10-15"
    />,
  );
  fireEvent.click(screen.getByRole("button"));

  expect(details()).toEqual([
    "BSE corporate actionsbse_corporate_actionsTier 2, exchange web endpoint.",
    "bse_resultsbse_resultsTier 2, exchange web endpoint.",
  ]);
});

test("figures read from no source carry no provenance chip", () => {
  const { container } = render(
    <ProvenanceChip sources={[]} isoDate="2026-10-15" />,
  );

  expect(container.childElementCount).toBe(0);
});
