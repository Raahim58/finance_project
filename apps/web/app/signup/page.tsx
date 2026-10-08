import Link from "next/link";

import { AuthForm } from "@/components/AuthForm";
import { AuthLayout } from "@/components/AuthLayout";

export default function SignupPage() {
  return (
    <AuthLayout title="Create your account" description="Start a portfolio workspace." legal="Investment mandate is set within your portfolio." footer={<><span>Already have an account?</span><Link className="rx-link" href="/login">Sign in</Link></>}>
      <AuthForm mode="signup" />
    </AuthLayout>
  );
}
