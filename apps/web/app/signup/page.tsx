import Link from "next/link";

import { AuthForm } from "@/components/AuthForm";
import { AuthLayout } from "@/components/AuthLayout";

export default function SignupPage() {
  return (
    <AuthLayout title="Create your workspace." description="Start with a guided investor profile, then define and govern each portfolio mandate." footer={<><span>Already have an account? </span><Link className="font-semibold text-accent" href="/login">Sign in</Link></>}>
      <AuthForm mode="signup" />
    </AuthLayout>
  );
}
