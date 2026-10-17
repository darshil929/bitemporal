import { redirect } from "next/navigation";

import { Disclaimer } from "@/components/layout/Disclaimer";
import { SignedOutHeader } from "@/components/layout/SignedOutHeader";
import { returnAddress } from "@/lib/return-address";
import { serverApiClient } from "@/lib/server-api-client";

import { NewPasswordForm } from "./NewPasswordForm";
import { SIGNED_OUT, sessionNotice } from "./notices";
import { SignInForm } from "./SignInForm";

type SignInPageProps = Readonly<{
  searchParams: Promise<{ next?: string; ended?: string }>;
}>;

// Setup comes first while no admin exists; someone already signed in goes on to where they were
// headed, once a temporary password is replaced here; otherwise the form, with why the previous
// session ended.
export default async function SignInPage({ searchParams }: SignInPageProps) {
  const { next: requested, ended } = await searchParams;
  const next = returnAddress(requested);
  const client = await serverApiClient();
  const setup = await client.GET("/setup");
  if (setup.data && !setup.data.admin_exists) {
    redirect("/setup");
  }
  const session = await client.GET("/session");
  const person = session.data;
  if (person && !person.must_change_password) {
    redirect(next);
  }
  // Signing out deletes the session's cookie, so a sign-out is known from the address alone.
  const notice =
    (session.error && sessionNotice(session.error.detail)) ??
    (ended === "signed_out" ? SIGNED_OUT : undefined);
  return (
    <>
      <SignedOutHeader />
      <main className="flex flex-wrap items-start justify-center gap-12 px-gutter pt-24 pb-30">
        {person ? (
          <NewPasswordForm displayName={person.display_name} next={next} />
        ) : (
          <SignInForm sessionNotice={notice} next={next} />
        )}
        <div className="w-[440px]">
          <Disclaimer />
        </div>
      </main>
    </>
  );
}
