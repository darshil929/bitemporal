import { redirect } from "next/navigation";

import { Disclaimer } from "@/components/layout/Disclaimer";
import { SignedOutHeader } from "@/components/layout/SignedOutHeader";
import { returnAddress } from "@/lib/return-address";
import { serverApiClient } from "@/lib/server-api-client";

import { sessionNotice } from "./notices";
import { SignInForm } from "./SignInForm";

type SignInPageProps = Readonly<{
  searchParams: Promise<{ next?: string }>;
}>;

// Setup comes first while no admin exists; someone already signed in goes on to where they were
// headed; otherwise the form, with why the previous session ended.
export default async function SignInPage({ searchParams }: SignInPageProps) {
  const next = returnAddress((await searchParams).next);
  const client = await serverApiClient();
  const setup = await client.GET("/setup");
  if (setup.data && !setup.data.admin_exists) {
    redirect("/setup");
  }
  const session = await client.GET("/session");
  // A temporary password is replaced here before any page opens.
  if (session.data && !session.data.must_change_password) {
    redirect(next);
  }
  const notice = session.error
    ? sessionNotice(session.error.detail)
    : undefined;
  return (
    <>
      <SignedOutHeader />
      <main className="flex flex-wrap items-start justify-center gap-12 px-gutter pt-24 pb-30">
        <SignInForm sessionNotice={notice} next={next} />
        <div className="w-[440px]">
          <Disclaimer />
        </div>
      </main>
    </>
  );
}
