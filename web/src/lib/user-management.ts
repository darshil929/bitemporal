import type { components } from "@/lib/api";

export type ManagedPerson = components["schemas"]["PersonResponse"];
export type SessionLimits = components["schemas"]["SessionLimitsResponse"];
export type AuditEntry = components["schemas"]["AuditEntryResponse"];

export const ROLE_LABELS: Record<ManagedPerson["role"], string> = {
  admin: "Admin",
  member: "Member",
};
