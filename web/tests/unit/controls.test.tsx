import { cleanup, render, screen, within } from "@testing-library/react";
import { Moon, MoreHorizontal } from "lucide-react";
import { afterEach, expect, test } from "vitest";

import { DateRange } from "@/components/controls/DateRange";
import { IconButton } from "@/components/controls/IconButton";
import { SearchField } from "@/components/controls/SearchField";
import {
  PrimaryMark,
  SegmentedControl,
} from "@/components/controls/SegmentedControl";
import { TextField } from "@/components/controls/TextField";

afterEach(cleanup);

const PAGE = "/instrument/INE040A01034";

test("a segmented control links each choice to its address and marks the one shown", () => {
  render(
    <SegmentedControl
      label="Venue"
      segments={[
        {
          label: "NSE",
          href: `${PAGE}?venue=NSE`,
          isSelected: true,
          marker: <PrimaryMark />,
        },
        { label: "BSE", href: `${PAGE}?venue=BSE` },
      ]}
    />,
  );

  const choices = within(screen.getByRole("group", { name: "Venue" }));
  const shown = choices.getByRole("link", { name: "NSE (primary)" });
  const other = choices.getByRole("link", { name: "BSE" });
  expect(shown.getAttribute("href")).toBe(`${PAGE}?venue=NSE`);
  expect(shown.getAttribute("aria-current")).toBe("true");
  expect(shown.classList).toContain("bg-surface");
  expect(other.getAttribute("href")).toBe(`${PAGE}?venue=BSE`);
  expect(other.hasAttribute("aria-current")).toBe(false);
  expect(other.classList).toContain("text-text-muted");
});

test("a disabled segment is shown but not offered", () => {
  render(
    <SegmentedControl
      label="Venue"
      segments={[
        { label: "BSE", href: `${PAGE}?venue=BSE`, isSelected: true },
        { label: "NSE", href: `${PAGE}?venue=NSE`, isDisabled: true },
      ]}
    />,
  );

  expect(screen.queryByRole("link", { name: "NSE" })).toBeNull();
  const disabled = screen.getByText("NSE");
  expect(disabled.getAttribute("aria-disabled")).toBe("true");
  expect(disabled.classList).toContain("text-border-strong");
});

test("the date range offers the price history's ranges in order, six months unless another is named", () => {
  const hrefFor = (range: string) => `${PAGE}?range=${range}`;
  const { rerender } = render(<DateRange hrefFor={hrefFor} />);

  const ranges = screen.getAllByRole("link");
  expect(ranges.map((range) => range.textContent)).toEqual([
    "1M",
    "3M",
    "6M",
    "1Y",
    "All",
  ]);
  expect(ranges.map((range) => range.getAttribute("href"))).toEqual(
    ["1M", "3M", "6M", "1Y", "All"].map(hrefFor),
  );
  expect(screen.getByRole("link", { current: true }).textContent).toBe("6M");

  rerender(<DateRange selected="1Y" hrefFor={hrefFor} />);
  expect(screen.getByRole("link", { current: true }).textContent).toBe("1Y");
});

test("a text field holds its value in tabular figures with its unit beside it", () => {
  const { container } = render(
    <TextField label="Return 3M above" defaultValue="2.00" unit="%" />,
  );

  const field = screen.getByRole("textbox", { name: "Return 3M above" });
  expect((field as HTMLInputElement).value).toBe("2.00");
  expect(container.firstElementChild?.textContent).toBe("%");
  expect(container.firstElementChild?.classList).toContain("tabular-nums");
  expect(container.firstElementChild?.classList).toContain(
    "focus-within:border-accent",
  );
});

test("a search field is named for what it searches and prompts with its placeholder", () => {
  render(
    <SearchField
      label="Search instruments"
      placeholder="Search name, symbol or ISIN"
    />,
  );

  const field = screen.getByRole("searchbox", { name: "Search instruments" });
  expect(field.getAttribute("placeholder")).toBe("Search name, symbol or ISIN");
});

test.each([
  ["bordered", "border-border"],
  ["plain", "border-transparent"],
] as const)("a %s icon button is named by what it does", (kind, edge) => {
  render(<IconButton icon={Moon} label="Use the dark theme" kind={kind} />);

  const button = screen.getByRole("button", { name: "Use the dark theme" });
  expect(button.classList).toContain(edge);
  expect(button.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
});

// Checked when the tests compile: an icon button cannot be written without a name.
export function UnnamedIconButton() {
  // @ts-expect-error a glyph alone says nothing to a screen reader
  return <IconButton icon={MoreHorizontal} />;
}
