import { cn } from "cn";
import { expect, test } from "vitest";

test("a type size stands beside a text colour", () => {
  expect(cn("text-title", "text-text-muted")).toBe(
    "text-title text-text-muted",
  );
  expect(cn("text-text", "text-cell")).toBe("text-text text-cell");
});

test("a later type size or colour replaces an earlier one", () => {
  expect(cn("text-sm text-body", "text-caption")).toBe("text-caption");
  expect(cn("text-text-muted", "text-text")).toBe("text-text");
});

test("the theme's spacing replaces the default scale", () => {
  expect(cn("h-9 px-4", "h-control px-3")).toBe("h-control px-3");
});
