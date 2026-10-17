import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { Button } from "@/components/controls/Button";
import { FormField } from "@/components/controls/FormField";
import { PasswordField } from "@/components/controls/PasswordField";
import { TextField } from "@/components/controls/TextField";
import { DISCLAIMER, Disclaimer } from "@/components/layout/Disclaimer";

afterEach(cleanup);

const RULE = "At least 15 characters";

function Password({ error }: Readonly<{ error?: string }>) {
  return (
    <FormField label="Password" help={RULE} error={error}>
      {({ isInvalid, ...control }) => (
        <PasswordField isInvalid={isInvalid} {...control} />
      )}
    </FormField>
  );
}

test("a field is named by its label and described by the rule it keeps", () => {
  render(<Password />);

  const field = screen.getByLabelText("Password");
  expect(field.getAttribute("type")).toBe("password");
  expect(field.hasAttribute("aria-invalid")).toBe(false);
  const rule = document.getElementById(
    field.getAttribute("aria-describedby") ?? "",
  );
  expect(rule?.textContent).toBe(RULE);
});

test("an error takes the rule's place, marks the field invalid and gives its box the flag", () => {
  render(<Password error="The two passwords differ" />);

  const field = screen.getByLabelText("Password");
  expect(field.getAttribute("aria-invalid")).toBe("true");
  const message = document.getElementById(
    field.getAttribute("aria-describedby") ?? "",
  );
  expect(message?.textContent).toBe("The two passwords differ");
  expect(message?.classList).toContain("text-flag");
  expect(screen.queryByText(RULE)).toBeNull();
  expect(field.parentElement?.classList).toContain("border-flag");
});

test("the eye shows the password typed and hides it again", () => {
  render(<Password />);
  const field = screen.getByLabelText("Password");

  fireEvent.click(screen.getByRole("button", { name: "Show password" }));
  expect(field.getAttribute("type")).toBe("text");
  expect(field.classList).toContain("font-mono");

  fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
  expect(field.getAttribute("type")).toBe("password");
});

test("a value changed elsewhere reads on the sunken surface, with who changes it beside the label", () => {
  render(
    <FormField label="Role" aside="Changed by an admin">
      {(control) => <TextField readOnly defaultValue="Member" {...control} />}
    </FormField>,
  );

  const field = screen.getByLabelText("Role");
  expect(field.hasAttribute("readonly")).toBe(true);
  expect(field.parentElement?.classList).toContain("bg-surface-sunken");
  expect(screen.getByText("Changed by an admin")).toBeDefined();
});

test("a busy button is held in its colours and announced as busy", () => {
  render(
    <Button kind="primary" isBusy>
      Signing in
    </Button>,
  );

  const button = screen.getByRole("button", { name: "Signing in" });
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(button.getAttribute("aria-busy")).toBe("true");
  expect(button.classList).toContain("bg-text");
  expect(button.classList).not.toContain("disabled:bg-surface-sunken");
  expect(button.querySelector(".motion-safe\\:animate-pulse")).not.toBeNull();
});

test("the disclaimer states what the output is and is not, under its heading", () => {
  render(<Disclaimer />);

  expect(screen.getByRole("heading", { name: "Disclaimer" })).toBeDefined();
  expect(screen.getByText(DISCLAIMER)).toBeDefined();
  expect(DISCLAIMER).toContain("not investment advice");
});
