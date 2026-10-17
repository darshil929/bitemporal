import { redirect } from "next/navigation";

import { Disclaimer } from "@/components/layout/Disclaimer";
import { SetupSteps } from "@/components/layout/SetupSteps";
import { SignedOutHeader } from "@/components/layout/SignedOutHeader";
import { serverApiClient } from "@/lib/server-api-client";

import { FirstAdminForm } from "./FirstAdminForm";

// Offered while the installation has no admin; once one exists there is nothing to set up.
export default async function SetupPage() {
  const { data } = await (await serverApiClient()).GET("/setup");
  if (!data) {
    throw new Error("The installation's setup could not be read");
  }
  if (data.admin_exists) {
    redirect("/");
  }
  return (
    <>
      <SignedOutHeader>
        <SetupSteps />
      </SignedOutHeader>
      <main className="flex flex-wrap items-start gap-gutter p-gutter">
        <FirstAdminForm />
        <div className="w-[440px]">
          <Disclaimer />
        </div>
      </main>
    </>
  );
}
