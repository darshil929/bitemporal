import Link from "next/link";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { requireSession } from "@/lib/page-access";
import { serverApiClient } from "@/lib/server-api-client";

import { PeopleTable } from "./PeopleTable";

// Account listing for admins; a member sees a refusal panel with a link back.
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
  const people = await api.GET("/admin/users");
  if (!people.data) {
    throw new Error("The people list could not be read");
  }
  return (
    <>
      <PageHeader title="Users" />
      <PeopleTable people={people.data} currentUserId={person.id} />
    </>
  );
}
