import { notFound } from "next/navigation";

import { PageHeader } from "@/components/layout/PageHeader";
import { formatDateTime } from "@/lib/format";
import { requireSession } from "@/lib/page-access";
import { serverApiClient } from "@/lib/server-api-client";

import { FiguresCard } from "./FiguresCard";
import { RunsCard } from "./RunsCard";

// The data status in full for admins: the day the pages show and what stands behind it, and the
// newest runs of the flows. Anyone else finds no page here.
export default async function DataStatusPage() {
  const person = await requireSession();
  if (person.role !== "admin") {
    notFound();
  }
  const api = await serverApiClient();
  const [status, history] = await Promise.all([
    api.GET("/data/status"),
    api.GET("/data/runs"),
  ]);
  if (!status.data || !history.data) {
    throw new Error("The data status could not be read");
  }
  return (
    <>
      <PageHeader
        title="Data status"
        trailing={
          <span className="text-header text-text-subtle tabular-nums">
            As on {formatDateTime(new Date().toISOString())}. Times in India
            time
          </span>
        }
      />
      <FiguresCard status={status.data} history={history.data} />
      <RunsCard runs={history.data.runs} />
    </>
  );
}
