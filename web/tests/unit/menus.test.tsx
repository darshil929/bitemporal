import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  DropdownMenuCheckboxItem,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuNote,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
} from "@/components/controls/DropdownMenu";
import { Select } from "@/components/controls/Select";

afterEach(cleanup);

// The menu measures its trigger as a browser does; the test DOM has no resize observer.
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  },
);

function open(name: string): HTMLElement {
  const trigger = screen.getByRole("button", { name });
  fireEvent.keyDown(trigger, { key: "Enter" });
  return trigger;
}

function Indicators({
  onCheckedChange = () => {},
}: Readonly<{ onCheckedChange?: (checked: boolean) => void }>) {
  return (
    <Select prefix="Indicators" value="SMA 50, SMA 200">
      <DropdownMenuLabel>Moving averages</DropdownMenuLabel>
      <DropdownMenuCheckboxItem
        checked={false}
        onCheckedChange={onCheckedChange}
      >
        SMA 20
      </DropdownMenuCheckboxItem>
      <DropdownMenuCheckboxItem checked>SMA 50</DropdownMenuCheckboxItem>
      <DropdownMenuCheckboxItem checked>SMA 200</DropdownMenuCheckboxItem>
      <DropdownMenuLabel>Bands</DropdownMenuLabel>
      <DropdownMenuCheckboxItem checked={false}>
        Bollinger 20, 2
      </DropdownMenuCheckboxItem>
      <DropdownMenuNote>Overlays share the price axis.</DropdownMenuNote>
    </Select>
  );
}

test("a select shows what is chosen and opens its menu from the keyboard", () => {
  render(<Indicators />);

  const trigger = open("Indicators SMA 50, SMA 200");

  expect(screen.getByRole("menu")).toBeDefined();
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  expect(trigger.className).toContain("data-[state=open]:border-accent");
});

test("several choices are ticked one by one under their labels, with a note beneath", () => {
  const onCheckedChange = vi.fn();
  render(<Indicators onCheckedChange={onCheckedChange} />);
  open("Indicators SMA 50, SMA 200");

  const choices = screen.getAllByRole("menuitemcheckbox");
  expect(choices.map((choice) => choice.getAttribute("aria-checked"))).toEqual([
    "false",
    "true",
    "true",
    "false",
  ]);
  // The tick shown is the last glyph, at the row's end; the base item's own sits hidden before it.
  const ticks = [...choices[1].querySelectorAll("svg")];
  expect(ticks.at(-1)?.classList).toContain("size-3.5");
  expect(choices[1].className).toContain("[&>span:first-child]:hidden");
  expect(choices[0].querySelector("svg")).toBeNull();
  expect(screen.getByText("Moving averages")).toBeDefined();
  expect(screen.getByText("Bands")).toBeDefined();
  expect(screen.getByText("Overlays share the price axis.")).toBeDefined();

  fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "SMA 20" }));
  expect(onCheckedChange).toHaveBeenCalledWith(true);
});

test("one choice among several is ticked where chosen, and choosing another reports it", () => {
  const onValueChange = vi.fn();
  const onSelect = vi.fn();
  render(
    <Select prefix="View" value="Rising with delivery">
      <DropdownMenuRadioGroup value="rising" onValueChange={onValueChange}>
        <DropdownMenuRadioItem value="rising">
          Rising with delivery
        </DropdownMenuRadioItem>
        <DropdownMenuRadioItem value="high">
          Near 52-week high
        </DropdownMenuRadioItem>
      </DropdownMenuRadioGroup>
      <DropdownMenuSeparator />
      <DropdownMenuItem onSelect={onSelect}>
        Save current view as
      </DropdownMenuItem>
    </Select>,
  );
  open("View Rising with delivery");

  const chosen = screen.getByRole("menuitemradio", {
    name: "Rising with delivery",
  });
  expect(chosen.getAttribute("aria-checked")).toBe("true");
  expect(chosen.className).toContain("data-[state=checked]:bg-surface-sunken");
  expect(screen.getByRole("separator")).toBeDefined();

  fireEvent.click(
    screen.getByRole("menuitemradio", { name: "Near 52-week high" }),
  );
  expect(onValueChange).toHaveBeenCalledWith("high");
});

test("an action reports when chosen, and the menu closes", () => {
  const onSelect = vi.fn();
  render(
    <Select value="Move beyond">
      <DropdownMenuItem caption="either way" onSelect={onSelect}>
        Move beyond
      </DropdownMenuItem>
    </Select>,
  );
  open("Move beyond");

  fireEvent.click(
    screen.getByRole("menuitem", { name: "Move beyond either way" }),
  );

  expect(onSelect).toHaveBeenCalledOnce();
  expect(screen.queryByRole("menu")).toBeNull();
});

test("escape closes an open menu", () => {
  render(<Indicators />);
  open("Indicators SMA 50, SMA 200");

  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });

  expect(screen.queryByRole("menu")).toBeNull();
});
