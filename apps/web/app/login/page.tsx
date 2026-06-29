import Link from "next/link";

import { AuthForm } from "@/components/AuthForm";

export default function LoginPage() {
  return (
    <section className="mx-auto grid max-w-md gap-5 px-5 py-12">
      <div>
        <h1 className="text-2xl font-semibold text-ink">Login</h1>
        <p className="mt-2 text-sm text-muted">Use your MVP account to access protected pages.</p>
      </div>
      <AuthForm mode="login" />
      <Link className="text-sm text-accent" href="/signup">
        Need an account?
      </Link>
    </section>
  );
}
