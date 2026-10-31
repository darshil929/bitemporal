import { expect, test } from "vitest";

import {
  type Criterion,
  FIGURES,
  type FigureName,
  readCriterion,
  thresholdFromTyped,
  thresholdText,
  typedThreshold,
  writeCriterion,
} from "@/lib/screener-criteria";

const figures = Object.keys(FIGURES) as FigureName[];

test("every figure's criterion reads back as written", () => {
  for (const figure of figures) {
    const criterion: Criterion = { figure, comparison: "lte", value: -0.0213 };

    expect(readCriterion(writeCriterion(criterion))).toEqual(criterion);
  }
  expect(
    writeCriterion({ figure: "adtv_20d", comparison: "gte", value: 2.5e8 }),
  ).toBe("adtv_20d:gte:250000000");
});

test("a part naming no figure, comparison or number reads as no criterion", () => {
  for (const part of [
    "close:gt:1",
    "return_3m:above:0",
    "return_3m:gt:",
    "return_3m:gt:many",
    "return_3m:gt",
    "is_52w_high:eq:true",
  ]) {
    expect(readCriterion(part)).toBeNull();
  }
});

test("a threshold reads in its figure's unit", () => {
  const read = (figure: FigureName, value: number) =>
    thresholdText({ figure, comparison: "gt", value });

  expect(read("adtv_20d", 250_000_000)).toBe("₹25 Cr");
  expect(read("adtv_20d", 20_000_000_000)).toBe("₹2,000 Cr");
  expect(read("adtv_20d", 125_000_000)).toBe("₹12.5 Cr");
  expect(read("return_3m", 0)).toBe("0.00%");
  expect(read("return_1d", 0.02)).toBe("2.00%");
  expect(read("from_52w_high", -0.05)).toBe("−5.00%");
  expect(read("delivery_pct_20d", 50)).toBe("50.0%");
  expect(read("rsi_14", 70)).toBe("70");
  expect(read("volume_ratio_20d", 1.5)).toBe("1.50×");
  expect(read("venue_spread_bps", 500)).toBe("500 bps");
});

test("a typed threshold is stored in the figure's own scale and typed back the same", () => {
  expect(thresholdFromTyped("return_1d", "2.13")).toBe(0.0213);
  expect(thresholdFromTyped("return_1d", "−5")).toBe(-0.05);
  expect(thresholdFromTyped("adtv_20d", "2,000")).toBe(20_000_000_000);
  expect(thresholdFromTyped("delivery_pct_20d", " 50 ")).toBe(50);
  expect(thresholdFromTyped("rsi_14", "")).toBeNull();
  expect(thresholdFromTyped("rsi_14", "high")).toBeNull();

  expect(
    typedThreshold({ figure: "return_3m", comparison: "gt", value: 0.0213 }),
  ).toBe("2.13");
  expect(
    typedThreshold({ figure: "adtv_20d", comparison: "gte", value: 2e10 }),
  ).toBe("2000");
});
