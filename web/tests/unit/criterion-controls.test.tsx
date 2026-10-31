import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { CriterionChip } from "@/components/controls/CriterionChip";
import { type Criterion, writeCriterion } from "@/lib/screener-criteria";

const navigation = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: navigation.push }),
}));

// The menu measures its trigger as a browser does; the test DOM has no resize observer.
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  },
);

beforeEach(() => navigation.push.mockClear());
afterEach(cleanup);

const SCREEN = "/screener?c=return_3m:gt:0";
const RISEN: Criterion = { figure: "return_3m", comparison: "gt", value: 0 };
const hrefFor = (criterion: Criterion) =>
  `/screener?c=${writeCriterion(criterion)}`;

function editRisen(): HTMLInputElement {
  render(
    <CriterionChip
      criterion={RISEN}
      removeHref="/screener"
      hrefFor={hrefFor}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Edit Return 3M above 0.00%" }),
  );
  return screen.getByRole<HTMLInputElement>("textbox", {
    name: "Return 3M threshold",
  });
}

test("a criterion chip reads its figure, comparison and threshold, and links to the screen without it", () => {
  render(
    <CriterionChip
      criterion={RISEN}
      removeHref="/screener"
      hrefFor={hrefFor}
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
      hrefFor={hrefFor}
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

test("an edited threshold applies on Enter and opens the screen with it", () => {
  const field = editRisen();

  expect(field.value).toBe("0.00");
  fireEvent.change(field, { target: { value: "2.5" } });
  fireEvent.keyDown(field, { key: "Enter" });

  expect(navigation.push).toHaveBeenCalledWith(
    hrefFor({ ...RISEN, value: 0.025 }),
    { scroll: false },
  );
  expect(screen.queryByRole("textbox")).toBeNull();
});

test("Escape leaves the criterion as it was", () => {
  const field = editRisen();

  fireEvent.change(field, { target: { value: "9" } });
  fireEvent.keyDown(field, { key: "Escape" });

  expect(navigation.push).not.toHaveBeenCalled();
  expect(
    screen.getByRole("group", { name: "Return 3M above 0.00%" }).textContent,
  ).toBe("Return 3M>0.00%");
});

test("a threshold that is no number is refused in place", () => {
  const field = editRisen();

  fireEvent.change(field, { target: { value: "high" } });
  fireEvent.keyDown(field, { key: "Enter" });

  expect(navigation.push).not.toHaveBeenCalled();
  expect(field.getAttribute("aria-invalid")).toBe("true");
});

test("a comparison chosen from its menu applies once focus leaves the chip", () => {
  const field = editRisen();

  fireEvent.keyDown(screen.getByRole("button", { name: "Comparison, above" }), {
    key: "Enter",
  });
  fireEvent.click(screen.getByRole("menuitemradio", { name: "≥ at or above" }));
  expect(navigation.push).not.toHaveBeenCalled();
  fireEvent.focusOut(field, { relatedTarget: document.body });

  expect(navigation.push).toHaveBeenCalledWith(
    hrefFor({ ...RISEN, comparison: "gte" }),
    { scroll: false },
  );
});
