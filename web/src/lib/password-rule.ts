// The password rule's refusals, in the words a password field shows under itself.
export const PASSWORD_PROBLEMS: Partial<Record<string, string>> = {
  too_short: "At least 15 characters",
  too_long: "At most 128 characters",
  contains_a_name:
    "The password may not contain the username, the display name or Bitemporal",
};

// A new password is typed twice; the two are compared before anything is sent.
export const PASSWORDS_DIFFER = "The two passwords differ";
