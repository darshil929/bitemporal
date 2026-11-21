import Link from "next/link";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { requireSession } from "@/lib/page-access";
import { serverApiClient } from "@/lib/server-api-client";

import { AuditLogCard } from "./AuditLogCard";
import { PeopleTable } from "./PeopleTable";
import { SessionLimitsCard } from "./SessionLimitsCard";

// Account listing, session limits, and audit trail for admins; a member sees a refusal panel.
export default async function UsersPage() {
  const person = await requireSession();
  if (person.role !== "admin") {
    return (
      <section className="rounded-sm border border-border bg-surface-raised p-5">
        <EmptyState
          title="Only an admin manages people"
          text={`This page lists every account and changes them. ${person.display_name} is a member.`}
          action={
            <Link href="/" className="text-cell text-accent hover:underline">
              Back to the dashboard
            </Link>
          }
        />
      </section>
    );
  }
  const api = await serverApiClient();
  const [people, settings, audit] = await Promise.all([
    api.GET("/admin/users"),
    api.GET("/admin/settings"),
    api.GET("/admin/audit"),
  ]);
  if (!people.data || !settings.data || !audit.data) {
    throw new Error("The people list could not be read");
  }
  return (
    <>
      <PageHeader title="Users" />
      <PeopleTable people={people.data} currentUserId={person.id} />
      <div className="grid grid-cols-1 items-start gap-section lg:grid-cols-[440px_minmax(0,1fr)]">
        <SessionLimitsCard limits={settings.data} />
        <AuditLogCard entries={audit.data} />
      </div>
    </>
  );
}
