import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { Button, type ButtonKind } from "@/components/controls/Button";

afterEach(cleanup);

function classesOf(name: string): string[] {
  return screen.getByRole("button", { name }).className.split(" ");
}

test.each<[ButtonKind, string[]]>([
  ["primary", ["border-text", "bg-text", "text-surface"]],
  ["secondary", ["border-border", "bg-surface-raised", "text-text"]],
  ["ghost", ["border-transparent", "bg-transparent", "text-text-muted"]],
])(
  "a %s button keeps its size and type beside its colours",
  (kind, colours) => {
    render(<Button kind={kind}>Retry</Button>);

    const classes = classesOf("Retry");
    expect(classes).toEqual(
      expect.arrayContaining([
        "h-control",
        "px-3",
        "rounded-sm",
        "text-cell",
        ...colours,
      ]),
    );
    expect(classes).not.toEqual(expect.arrayContaining(["h-9"]));
    expect(classes).not.toEqual(expect.arrayContaining(["text-sm"]));
    expect(classes).not.toEqual(expect.arrayContaining(["rounded-md"]));
  },
);

test("a button is secondary unless named otherwise", () => {
  render(<Button>Open watchlist</Button>);

  expect(classesOf("Open watchlist")).toEqual(
    expect.arrayContaining(["bg-surface-raised", "text-text"]),
  );
});
