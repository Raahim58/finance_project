import Link from "next/link";

import { AuthForm } from "@/components/AuthForm";
import { AuthLayout } from "@/components/AuthLayout";

export default function LoginPage() {
  return (
    <AuthLayout title="Welcome back" description="Sign in to your portfolio workspace" footer={<><span>Don’t have an account?</span><Link className="rx-link" href="/signup">Create account</Link></>}>
      <AuthForm mode="login" />
    </AuthLayout>
  );
}
