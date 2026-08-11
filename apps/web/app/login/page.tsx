import Link from "next/link";

import { AuthForm } from "@/components/AuthForm";
import { AuthLayout } from "@/components/AuthLayout";

export default function LoginPage() {
  return (
    <AuthLayout title="Welcome back." description="Sign in to review portfolios, risk, evidence and active decisions." footer={<><span>New to the workstation? </span><Link className="font-semibold text-accent" href="/signup">Create an account</Link></>}>
      <AuthForm mode="login" />
    </AuthLayout>
  );
}
