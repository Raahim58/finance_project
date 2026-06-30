import Link from "next/link";

export default function DashboardPage() {
  return (
    <section className="mx-auto grid max-w-6xl gap-6 px-5 py-8">
      <div>
        <h1 className="text-2xl font-semibold text-ink">Dashboard</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
          Phase 1 is focused on account setup, encrypted LLM keys, and preferences. Market,
          portfolio, RAG, policy, digest, and order-intent modules are queued for later phases.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-5">
        {[
          ["Auth", "Signup, login, and protected API routes are available."],
          ["LLM keys", "Save BYOK credentials without exposing decrypted secrets to the UI."],
          ["Preferences", "Set risk tolerance, horizon, sectors, and analysis modes."],
          ["Market", "View seeded mock PSX snapshot, rankings, sectors, and company history."],
          ["Portfolio", "Add holdings and review value, exposure, PnL, and risk flags."],
          ["Documents", "Upload company text/PDF files and search cited RAG chunks."]
        ].map(([title, body]) => (
          <div key={title} className="rounded-lg border border-line bg-white p-5">
            <h2 className="text-base font-semibold text-ink">{title}</h2>
            <p className="mt-2 text-sm leading-6 text-muted">{body}</p>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        <Link className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white" href="/market">
          Open market
        </Link>
        <Link className="w-fit rounded-md border border-line bg-white px-4 py-2 text-sm font-semibold text-ink" href="/portfolio">
          Open portfolio
        </Link>
        <Link className="w-fit rounded-md border border-line bg-white px-4 py-2 text-sm font-semibold text-ink" href="/documents">
          Open documents
        </Link>
        <Link className="w-fit rounded-md border border-line bg-white px-4 py-2 text-sm font-semibold text-ink" href="/settings">
          Open settings
        </Link>
      </div>
    </section>
  );
}
