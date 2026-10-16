import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { BpsCell } from "@/components/values/BpsCell";
import { CompactValue } from "@/components/values/CompactValue";
import { DeltaCell } from "@/components/values/DeltaCell";
import { PriceCell } from "@/components/values/PriceCell";
import { StaleValue } from "@/components/values/StaleValue";

afterEach(cleanup);

// The tooltip measures its trigger as a browser does; the test DOM has no resize observer.
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  },
);

const NO_DELIVERY = "No delivery file for this day";

function lighter(container: HTMLElement): string[] {
  return [...container.querySelectorAll(".text-text-subtle")].map(
    (part) => part.textContent ?? "",
  );
}

test("a price reads in tabular figures with its symbol one step lighter", () => {
  const { container } = render(
    <PriceCell value={1570.4} nullReason={NO_DELIVERY} />,
  );

  const cell = container.firstElementChild;
  expect(cell?.textContent).toBe("₹1,570.40");
  expect(cell?.classList.contains("tabular-nums")).toBe(true);
  expect(lighter(container)).toEqual(["₹"]);
});

test("an absent price is a dash that says why when focused", async () => {
  render(<PriceCell value={null} nullReason={NO_DELIVERY} />);

  const dash = screen.getByLabelText(NO_DELIVERY);
  fireEvent.focus(dash);

  expect(dash.textContent).toBe("—");
  expect((await screen.findByRole("tooltip")).textContent).toBe(NO_DELIVERY);
});

test("a price still loading is a skeleton hidden from assistive technology", () => {
  const { container } = render(
    <PriceCell value={null} nullReason={NO_DELIVERY} isLoading />,
  );

  expect(container.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
});

test.each([
  [0.0199, "return", "+1.99%", "text-up"],
  [-0.0038, "return", "−0.38%", "text-down"],
  [0, "return", "0.00%", "text-text"],
  [-6.2, "change", "−6.20", "text-down"],
] as const)("%s as a %s reads %s in %s", (value, kind, text, tone) => {
  const { container } = render(
    <DeltaCell value={value} kind={kind} nullReason={NO_DELIVERY} />,
  );

  const cell = container.firstElementChild;
  expect(cell?.textContent).toBe(text);
  expect(cell?.classList.contains(tone)).toBe(true);
});

test.each([
  [10_882_483_821.4, "large_value", "₹1,088.25Cr", ["₹", "Cr"]],
  [5_772_000, "volume", "57.72L", ["L"]],
  [1.56, "multiple", "1.56×", ["×"]],
  [64.2, "delivery_share", "64.2%", []],
] as const)("%s as a %s reads %s", (value, kind, text, parts) => {
  const { container } = render(
    <CompactValue value={value} kind={kind} nullReason={NO_DELIVERY} />,
  );

  expect(container.firstElementChild?.textContent).toBe(text);
  expect(lighter(container)).toEqual(parts);
});

test("a spread within the limit reads plainly with its unit lighter", () => {
  const { container } = render(
    <BpsCell value={6} isDiverging={false} nullReason={NO_DELIVERY} />,
  );

  expect(container.firstElementChild?.textContent).toBe("6bps");
  expect(lighter(container)).toEqual(["bps"]);
  expect(container.querySelector("svg")).toBeNull();
});

test("a diverging spread carries the flag, its unit in the flag's colour", () => {
  const { container } = render(
    <BpsCell value={612} isDiverging nullReason={NO_DELIVERY} />,
  );

  const pill = container.firstElementChild;
  expect(pill?.classList).toContain("bg-flag-surface");
  expect(pill?.classList).toContain("text-flag");
  expect(pill?.querySelector("svg")).not.toBeNull();
  expect(screen.getByText("Diverging:")).toBeTruthy();
  expect(lighter(container)).toEqual([]);
});

test("a stale price carries the day it is from before it", () => {
  const { container } = render(
    <StaleValue value={9331} isoDate="2025-06-13" />,
  );

  expect(container.firstElementChild?.textContent).toBe("13 Jun₹9,331.00");
  expect(screen.getByText("13 Jun").classList).toContain("text-text-muted");
});
