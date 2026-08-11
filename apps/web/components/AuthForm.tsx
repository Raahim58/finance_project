"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { login, setToken, signup } from "@/lib/api";

type AuthFormProps = {
  mode: "login" | "signup";
};

export function AuthForm({ mode }: AuthFormProps) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response =
        mode === "signup" ? await signup(email, password, fullName) : await login(email, password);
      setToken(response.access_token);
      router.push((mode === "signup" ? "/onboarding" : "/dashboard") as never);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-5" aria-busy={loading}>
      {mode === "signup" ? (
        <label className="field-label">
          Full name
          <input
            className="field"
            autoComplete="name"
            required
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
        </label>
      ) : null}
      <label className="field-label">
        Email
        <input
          className="field"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </label>
      <label className="field-label">
        Password
        <input
          className="field"
          type="password"
          autoComplete={mode === "signup" ? "new-password" : "current-password"}
          required
          minLength={8}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>
      {mode === "signup" ? <p className="-mt-2 text-[11px] leading-5 text-muted">Use at least 8 characters. Your account protects portfolio and provider-key access.</p> : null}
      {error ? <p className="notice notice-error" role="alert">{error}</p> : null}
      <button
        className="btn btn-primary min-h-11 w-full"
        disabled={loading}
        type="submit"
      >
        {loading ? "Working…" : mode === "signup" ? "Create account" : "Sign in"}
      </button>
    </form>
  );
}
