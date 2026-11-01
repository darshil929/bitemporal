import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { BreadthBar } from "@/components/tables/BreadthBar";
import { Sparkline } from "@/components/tables/Sparkline";
import { Stat } from "@/components/tables/Stat";

afterEach(cleanup);

test("a stat names its figure, keyed in the colour its instruments take", () => {
  render(
    <dl>
      <Stat label="Advancing" keyColour="up">
        1,464
      </Stat>
      <Stat label="Median change">−1.25%</Stat>
    </dl>,
  );

  const advancing = screen.getByText("Advancing");
  expect(advancing.tagName).toBe("DT");
  expect(advancing.querySelector(".bg-up")).not.toBeNull();
  const figure = screen.getByText("1,464");
  expect(figure.tagName).toBe("DD");
  expect(figure.classList).toContain("text-summary");
  expect(screen.getByText("Median change").querySelector("span")).toBeNull();
});

test("a sparkline runs 2 px inside its frame and marks the last close", () => {
  const { container } = render(
    <Sparkline closes={[100, 110, 105, 120]} width={96} height={24} />,
  );

  expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe(
    "true",
  );
  expect(container.querySelector("polyline")?.getAttribute("points")).toBe(
    "2.0,22.0 32.7,12.0 63.3,17.0 94.0,2.0",
  );
  const end = container.querySelector("circle");
  expect([end?.getAttribute("cx"), end?.getAttribute("cy")]).toEqual([
    "94.0",
    "2.0",
  ]);
});

test("a level run draws a level line, and fewer than two closes draw nothing", () => {
  const { container, rerender } = render(<Sparkline closes={[50, 50, 50]} />);

  expect(container.querySelector("polyline")?.getAttribute("points")).toBe(
    "2.0,2.0 48.0,2.0 94.0,2.0",
  );

  rerender(<Sparkline closes={[50]} />);
  expect(container.innerHTML).toBe("");
});

test("the breadth bar gives each count a part as wide as its share, none for a count of none", () => {
  const { container, rerender } = render(
    <BreadthBar advancing={1464} declining={3230} unchanged={188} />,
  );
  const parts = () =>
    [...container.querySelectorAll<HTMLElement>("[data-part]")].map((part) => [
      part.dataset.part,
      part.style.flexGrow,
      part.className,
    ]);

  expect(parts()).toEqual([
    ["advancing", "1464", "bg-up"],
    ["declining", "3230", "bg-down"],
    ["unchanged", "188", "bg-border-strong"],
  ]);

  rerender(<BreadthBar advancing={28} declining={6} unchanged={0} />);
  expect(parts().map(([part]) => part)).toEqual(["advancing", "declining"]);
});
