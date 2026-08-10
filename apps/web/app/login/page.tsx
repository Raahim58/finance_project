import Link from "next/link";

import { AuthForm } from "@/components/AuthForm";

export default function LoginPage() {
  return (
    <section className="mx-auto grid min-h-screen max-w-md content-center gap-5 px-5 py-12">
      <div>
        <p className="eyebrow">PSX Workstation</p><h1 className="page-title mt-2">Sign in</h1>
        <p className="mt-2 text-sm text-muted">Access your private investment workspace.</p>
      </div>
      <AuthForm mode="login" />
      <Link className="text-sm text-accent" href="/signup">
        Need an account?
      </Link>
    </section>
  );
}
