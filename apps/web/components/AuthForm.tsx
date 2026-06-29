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
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4 rounded-lg border border-line bg-white p-5">
      {mode === "signup" ? (
        <label className="grid gap-2 text-sm text-ink">
          Full name
          <input
            className="rounded-md border border-line px-3 py-2"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
        </label>
      ) : null}
      <label className="grid gap-2 text-sm text-ink">
        Email
        <input
          className="rounded-md border border-line px-3 py-2"
          type="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </label>
      <label className="grid gap-2 text-sm text-ink">
        Password
        <input
          className="rounded-md border border-line px-3 py-2"
          type="password"
          required
          minLength={8}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>
      {error ? <p className="text-sm text-warn">{error}</p> : null}
      <button
        className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
        disabled={loading}
        type="submit"
      >
        {loading ? "Working..." : mode === "signup" ? "Create account" : "Login"}
      </button>
    </form>
  );
}
