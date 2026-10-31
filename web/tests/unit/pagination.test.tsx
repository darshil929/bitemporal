import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { Pagination } from "@/components/controls/Pagination";

afterEach(cleanup);

const SCREEN = "/screener?c=return_3m:gt:0";

test("the pages reach the row cap, with no page before the first or after the last", () => {
  const hrefFor = (page: number) => `${SCREEN}&page=${page}`;
  const { rerender } = render(
    <Pagination
      page={1}
      pageSize={50}
      matched={641}
      rowCap={500}
      hrefFor={hrefFor}
    />,
  );

  const pages = within(screen.getByRole("navigation", { name: "Pages" }));
  expect(pages.getByText("Rows 1–50 of 500")).toBeTruthy();
  expect(pages.queryByRole("link", { name: "Previous page" })).toBeNull();
  expect(
    pages.getByLabelText("Previous page").getAttribute("aria-disabled"),
  ).toBe("true");
  expect(
    pages.getByRole("link", { name: "Next page" }).getAttribute("href"),
  ).toBe(hrefFor(2));

  rerender(
    <Pagination
      page={10}
      pageSize={50}
      matched={641}
      rowCap={500}
      hrefFor={hrefFor}
    />,
  );
  expect(pages.getByText("Rows 451–500 of 500")).toBeTruthy();
  expect(
    pages.getByRole("link", { name: "Previous page" }).getAttribute("href"),
  ).toBe(hrefFor(9));
  expect(pages.queryByRole("link", { name: "Next page" })).toBeNull();
});

test("one page has no page to open, and an empty screen shows no pages", () => {
  const hrefFor = (page: number) => `${SCREEN}&page=${page}`;
  const { rerender } = render(
    <Pagination
      page={1}
      pageSize={50}
      matched={15}
      rowCap={500}
      hrefFor={hrefFor}
    />,
  );

  expect(screen.getByText("Rows 1–15 of 15")).toBeTruthy();
  expect(screen.queryAllByRole("link")).toEqual([]);

  rerender(
    <Pagination
      page={1}
      pageSize={50}
      matched={0}
      rowCap={500}
      hrefFor={hrefFor}
    />,
  );
  expect(screen.queryByRole("navigation")).toBeNull();
});
