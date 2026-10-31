import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { CriterionChip } from "@/components/controls/CriterionChip";

afterEach(cleanup);

const SCREEN = "/screener?c=return_3m:gt:0";

test("a criterion chip reads its figure, comparison and threshold, and links to the screen without it", () => {
  render(
    <CriterionChip
      criterion={{ figure: "return_3m", comparison: "gt", value: 0 }}
      removeHref="/screener"
    />,
  );

  const chip = screen.getByRole("group", { name: "Return 3M above 0.00%" });
  expect(chip.textContent).toBe("Return 3M>0.00%");
  expect(chip.classList).toContain("bg-surface-raised");
  const remove = within(chip).getByRole("link", {
    name: "Remove Return 3M above 0.00%",
  });
  expect(remove.getAttribute("href")).toBe("/screener");
});

test("the gate's chip sits on the sunken surface and its removal is named for the gate", () => {
  render(
    <CriterionChip
      criterion={{ figure: "adtv_20d", comparison: "gte", value: 250_000_000 }}
      isGate
      removeHref={`${SCREEN}&gate=none`}
    />,
  );

  const chip = screen.getByRole("group", {
    name: "Liquidity gate, ADTV 20D at or above ₹25 Cr",
  });
  expect(chip.classList).toContain("bg-surface-sunken");
  expect(
    within(chip)
      .getByRole("link", { name: "Remove the liquidity gate" })
      .getAttribute("href"),
  ).toBe(`${SCREEN}&gate=none`);
});
