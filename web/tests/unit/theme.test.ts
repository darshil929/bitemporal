import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, test } from "vitest";

const SOURCE = path.resolve(__dirname, "../../src");
const THEME = path.join(SOURCE, "app", "globals.css");

const COLOURS = [
  "surface",
  "surface-raised",
  "surface-sunken",
  "border",
  "border-strong",
  "text",
  "text-muted",
  "text-subtle",
  "up",
  "down",
  "flag",
  "flag-surface",
  "flag-border",
  "stale",
  "accent",
];

// Colours that carry a value or a label, each read against the surfaces it sits on.
const INKS = [
  "text",
  "text-muted",
  "text-subtle",
  "up",
  "down",
  "flag",
  "stale",
  "accent",
];
const SURFACES = ["surface", "surface-raised"];

// WCAG AA for text below 18 points.
const MINIMUM_CONTRAST = 4.5;

const COLOUR_LITERAL =
  /#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch|color-mix)\(/i;

function colours(block: string): Map<string, string> {
  return new Map(
    [...block.matchAll(/--color-([a-z-]+):\s*(#[0-9A-Fa-f]{6});/g)].map(
      ([, name, value]) => [name, value],
    ),
  );
}

function block(css: string, opening: string): string {
  const start = css.indexOf(opening);
  return start < 0 ? "" : css.slice(start, css.indexOf("}", start));
}

function luminance(hex: string): number {
  const [red, green, blue] = [1, 3, 5].map((offset) => {
    const channel = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return channel <= 0.04045
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrast(first: string, second: string): number {
  const [lighter, darker] = [luminance(first), luminance(second)].sort(
    (a, b) => b - a,
  );
  return (lighter + 0.05) / (darker + 0.05);
}

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = path.join(directory, entry.name);
    return entry.isDirectory() ? sourceFiles(entryPath) : [entryPath];
  });
}

const css = readFileSync(THEME, "utf8");
const themes = {
  light: colours(block(css, "@theme static {")),
  dark: colours(block(css, '[data-theme="dark"] {')),
};

describe.each(Object.entries(themes))("the %s theme", (_, theme) => {
  test("defines every colour", () => {
    expect([...theme.keys()].sort()).toEqual([...COLOURS].sort());
  });

  test("reads every ink at AA on the page and card surfaces", () => {
    for (const ink of INKS) {
      for (const surface of SURFACES) {
        const ratio = contrast(theme.get(ink) ?? "", theme.get(surface) ?? "");
        expect(ratio, `${ink} on ${surface}`).toBeGreaterThanOrEqual(
          MINIMUM_CONTRAST,
        );
      }
    }
  });

  test("reads a flag at AA on its own surface", () => {
    const ratio = contrast(
      theme.get("flag") ?? "",
      theme.get("flag-surface") ?? "",
    );
    expect(ratio).toBeGreaterThanOrEqual(MINIMUM_CONTRAST);
  });
});

test("colours are written in the theme alone", () => {
  const holding = sourceFiles(SOURCE).filter((file) =>
    COLOUR_LITERAL.test(readFileSync(file, "utf8")),
  );

  expect(holding).toEqual([THEME]);
});
