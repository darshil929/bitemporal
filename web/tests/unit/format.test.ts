import { describe, expect, test } from "vitest";

import {
  asText,
  direction,
  formatBps,
  formatChange,
  formatDate,
  formatDateTime,
  formatDeliveryShare,
  formatDividend,
  formatLargeValue,
  formatMultiple,
  formatPrice,
  formatReturn,
  formatShortDate,
  formatVolume,
} from "@/lib/format";

const MINUS = "−";

describe("figures", () => {
  test.each([
    ["a price", formatPrice(1234.56), { prefix: "₹", text: "1,234.56" }],
    [
      "a price in Indian grouping",
      formatPrice(12345678.9),
      { prefix: "₹", text: "1,23,45,678.90" },
    ],
    [
      "a price rounded half up",
      formatPrice(0.125),
      { prefix: "₹", text: "0.13" },
    ],
    [
      "a value below a lakh",
      formatLargeValue(84231),
      { prefix: "₹", text: "84,231" },
    ],
    [
      "a value of a lakh",
      formatLargeValue(100000),
      { prefix: "₹", text: "1.00", unit: "L" },
    ],
    [
      "a value in lakh",
      formatLargeValue(320000),
      { prefix: "₹", text: "3.20", unit: "L" },
    ],
    [
      "a value in crore",
      formatLargeValue(124500000),
      { prefix: "₹", text: "12.45", unit: "Cr" },
    ],
    ["a volume below a lakh", formatVolume(84231), { text: "84,231" }],
    ["a volume in crore", formatVolume(14200000), { text: "1.42", unit: "Cr" }],
    ["a rise", formatChange(15.3), { text: "+15.30" }],
    ["a fall", formatChange(-2.05), { text: `${MINUS}2.05` }],
    ["no change", formatChange(0), { text: "0.00" }],
    ["a change rounding to nothing", formatChange(-0.004), { text: "0.00" }],
    ["a return", formatReturn(0.0124), { text: "+1.24%" }],
    ["a negative return", formatReturn(-0.0087), { text: `${MINUS}0.87%` }],
    ["basis points", formatBps(24.4), { text: "24", unit: "bps" }],
    ["a delivery share", formatDeliveryShare(43.21), { text: "43.2%" }],
    ["a multiple", formatMultiple(1.556), { text: "1.56", unit: "×" }],
    ["a dividend", formatDividend(22), { prefix: "₹", text: "22.00" }],
    [
      "a dividend below a paisa",
      formatDividend(0.125),
      { prefix: "₹", text: "0.125" },
    ],
    [
      "a dividend of a tenth of a paisa",
      formatDividend(0.001),
      { prefix: "₹", text: "0.001" },
    ],
  ])("%s", (_, formatted, expected) => {
    expect(formatted).toEqual(expected);
  });
});

describe("days and moments", () => {
  test("a day reads day, short month, year", () => {
    expect(formatDate("2026-09-16")).toBe("16 Sep 2026");
  });

  test("a day beside a figure reads day and short month", () => {
    expect(formatShortDate("2025-06-13")).toBe("13 Jun");
  });

  test("a moment reads in India time", () => {
    expect(formatDateTime("2026-09-16T08:35:00Z")).toBe("16 Sep 2026, 14:05");
  });

  test("a moment late in the evening in UTC is the next day in India", () => {
    expect(formatDateTime("2026-10-10T19:30:00Z")).toBe("11 Oct 2026, 01:00");
  });
});

describe("sign and text", () => {
  test.each([
    [formatChange(15.3), "up"],
    [formatReturn(-0.0087), "down"],
    [formatChange(-0.004), "flat"],
  ] as const)("%o moves %s", (formatted, expected) => {
    expect(direction(formatted)).toBe(expected);
  });

  test.each([
    [formatPrice(1234.56), "₹1,234.56"],
    [formatLargeValue(320000), "₹3.20 L"],
    [formatBps(24), "24 bps"],
    [formatMultiple(142.3), "142.30×"],
  ])("%o reads %s", (formatted, expected) => {
    expect(asText(formatted)).toBe(expected);
  });
});
