import Link from "next/link";

import { AuthForm } from "@/components/AuthForm";

export default function SignupPage() {
  return (
    <section className="mx-auto grid min-h-screen max-w-md content-center gap-5 px-5 py-12">
      <div>
        <p className="eyebrow">PSX Workstation</p><h1 className="page-title mt-2">Create account</h1>
        <p className="mt-2 text-sm text-muted">Start with a guided investor mandate, then build your portfolio.</p>
      </div>
      <AuthForm mode="signup" />
      <Link className="text-sm text-accent" href="/login">
        Already have an account?
      </Link>
    </section>
  );
}
