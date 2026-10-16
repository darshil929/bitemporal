import { cleanup, render, screen } from "@testing-library/react";
import { Info } from "lucide-react";
import { afterEach, expect, test } from "vitest";

import { ActionMarker } from "@/components/status/ActionMarker";
import { AlertStatus } from "@/components/status/AlertStatus";
import { DayCompleteness } from "@/components/status/DayCompleteness";
import { NoteChip } from "@/components/status/NoteChip";
import { StalePill } from "@/components/status/StalePill";
import { StatusPill } from "@/components/status/StatusPill";
import { VenueBadge } from "@/components/status/VenueBadge";

afterEach(cleanup);

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
