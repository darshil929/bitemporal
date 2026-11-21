import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ConfirmDialog } from "@/components/layout/ConfirmDialog";
import { Dialog, DialogActions } from "@/components/layout/Dialog";

afterEach(cleanup);

test("a dialog shows its title, subtitle, body, and footer, and closes on its close button", () => {
  const onOpenChange = vi.fn();
  render(
    <Dialog
      open
      onOpenChange={onOpenChange}
      title="Add a person"
      subtitle="Temporary password shown once"
      footer={<DialogActions right={<span>Action slot</span>} />}
    >
      <p>Dialog body text</p>
    </Dialog>,
  );

  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(screen.getByText("Add a person")).toBeTruthy();
  expect(screen.getByText("Temporary password shown once")).toBeTruthy();
  expect(screen.getByText("Dialog body text")).toBeTruthy();
  expect(screen.getByText("Action slot")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

test("a dialog blocks dismissal while canClose is false", () => {
  const onOpenChange = vi.fn();
  render(
    <Dialog open onOpenChange={onOpenChange} title="Running" canClose={false}>
      <p>Busy body</p>
    </Dialog>,
  );

  const close = screen.getByRole("button", { name: "Close" });
  expect((close as HTMLButtonElement).disabled).toBe(true);
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(onOpenChange).not.toHaveBeenCalled();
});

test("a confirm dialog lists each change, calls onConfirm, and shows busy and error states", () => {
  const onConfirm = vi.fn();
  const onOpenChange = vi.fn();
  const { rerender } = render(
    <ConfirmDialog
      open
      onOpenChange={onOpenChange}
      title="Disable Meera"
      description="Meera is signed out at once."
      changes={[
        "Every session of Meera ends now",
        "Watchlists, views and alerts are kept",
      ]}
      confirmLabel="Disable account"
      busyLabel="Disabling"
      onConfirm={onConfirm}
    />,
  );

  expect(screen.getByText("Disable Meera")).toBeTruthy();
  expect(screen.getByText("Meera is signed out at once.")).toBeTruthy();
  expect(screen.getByText("Every session of Meera ends now")).toBeTruthy();
  expect(
    screen.getByText("Watchlists, views and alerts are kept"),
  ).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Disable account" }));
  expect(onConfirm).toHaveBeenCalledTimes(1);

  rerender(
    <ConfirmDialog
      open
      onOpenChange={onOpenChange}
      title="Disable Meera"
      description="Meera is signed out at once."
      changes={["Every session of Meera ends now"]}
      confirmLabel="Disable account"
      busyLabel="Disabling"
      isBusy
      error="The change could not be saved. Try again."
      onConfirm={onConfirm}
    />,
  );

  const busy = screen.getByRole("button", { name: "Disabling" });
  expect((busy as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByRole("alert").textContent).toContain(
    "The change could not be saved. Try again.",
  );
});
