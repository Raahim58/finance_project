"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { login, setToken, signup, startSampleSession } from "@/lib/api";

type AuthFormProps = {
  mode: "login" | "signup";
};

export function AuthForm({ mode }: AuthFormProps) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === "signup" && password !== confirm) { setError("Passwords do not match."); return; }
    setLoading(true);
    setError(null);
    try {
      const response = mode === "signup" ? await signup(email, password, fullName) : await login(email, password);
      setToken(response.access_token);
      router.push((mode === "signup" ? "/onboarding" : "/dashboard") as never);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  async function openDemo() {
    setLoading(true);
    setError(null);
    try {
      setToken((await startSampleSession()).access_token);
      router.push("/dashboard" as never);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Demo workspace unavailable");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <form onSubmit={onSubmit} style={{ display: "grid", gap: 20 }} aria-busy={loading}>
        {mode === "signup" ? (
          <label className="rx-label">Name
            <input className="rx-input" autoComplete="name" required value={fullName} onChange={event => setFullName(event.target.value)} />
          </label>
        ) : null}
        <label className="rx-label">Email
          <input className="rx-input" type="email" autoComplete="email" required placeholder={mode === "login" ? "Enter your email" : undefined} value={email} onChange={event => setEmail(event.target.value)} />
        </label>
        <label className="rx-label">Password
          <input className="rx-input" type="password" autoComplete={mode === "signup" ? "new-password" : "current-password"} required minLength={8} placeholder={mode === "login" ? "Enter your password" : undefined} value={password} onChange={event => setPassword(event.target.value)} />
        </label>
        {mode === "signup" ? (
          <label className="rx-label">Confirm password
            <input className="rx-input" type="password" autoComplete="new-password" required minLength={8} value={confirm} onChange={event => setConfirm(event.target.value)} />
          </label>
        ) : null}
        {error ? <p className="rx-error" role="alert">{error}</p> : null}
        <button className="rx-btn" disabled={loading} type="submit">{loading ? "Working…" : mode === "signup" ? "Create account" : "Sign in"}</button>
      </form>
      {mode === "login" ? (
        <div className="rx-auth-alt"><button type="button" className="rx-link-quiet" style={{ background: "none", border: 0, cursor: "pointer", font: "inherit" }} onClick={openDemo} disabled={loading}>Open demo workspace</button></div>
      ) : null}
    </>
  );
}
