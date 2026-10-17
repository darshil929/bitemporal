import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import DashboardPage from "@/app/(app)/page";

test("dashboard renders its heading", () => {
  render(<DashboardPage />);

  expect(
    screen.getByRole("heading", { level: 1, name: "Market" }),
  ).toBeDefined();
});
