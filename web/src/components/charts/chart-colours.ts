// A chart draws on a canvas, which takes colours as values rather than the theme's names, so the
// chart reads the values the theme holds now.
const THEME_COLOURS = {
  surfaceRaised: "surface-raised",
  border: "border",
  borderStrong: "border-strong",
  textMuted: "text-muted",
  textSubtle: "text-subtle",
  up: "up",
  down: "down",
  flag: "flag",
  flagSurface: "flag-surface",
} as const;

export type ChartColours = Record<keyof typeof THEME_COLOURS, string>;

export function chartColours(): ChartColours {
  const theme = getComputedStyle(document.documentElement);
  return Object.fromEntries(
    Object.entries(THEME_COLOURS).map(([key, name]) => [
      key,
      theme.getPropertyValue(`--color-${name}`).trim(),
    ]),
  ) as ChartColours;
}

// Calls back whenever the page switches between light and dark.
export function onThemeChange(callback: () => void): () => void {
  const observer = new MutationObserver(callback);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  return () => observer.disconnect();
}
