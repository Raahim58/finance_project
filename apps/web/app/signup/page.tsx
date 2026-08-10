import Link from "next/link";

import { AuthForm } from "@/components/AuthForm";

export default function SignupPage() {
  return (
    <section className="mx-auto grid max-w-md gap-5 px-5 py-12">
      <div>
        <h1 className="text-2xl font-semibold text-ink">Create account</h1>
        <p className="mt-2 text-sm text-muted">Create your private workstation account.</p>
      </div>
      <AuthForm mode="signup" />
      <Link className="text-sm text-accent" href="/login">
        Already have an account?
      </Link>
    </section>
  );
}
