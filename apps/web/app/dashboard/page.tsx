import Link from "next/link";

export default function DashboardPage() {
  return (
    <section className="mx-auto grid max-w-6xl gap-6 px-5 py-8">
      <div>
        <h1 className="text-2xl font-semibold text-ink">Dashboard</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
          Monitor portfolio value, data freshness, research evidence, recommendations, and alerts from one grounded workstation.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-5">
        {[
          ["Portfolios", "Maintain independent ledgers, IPS versions, allocations, scenarios, and monitoring."],
          ["Quant", "Inspect reproducible risk, covariance, tail loss, contributions, and optimizer proposals."],
          ["Markets", "View database-backed PSX prices with provider and freshness evidence."],
          ["Research", "Search public and private documents with page-level citations."],
          ["Assistant", "Ask questions through allowlisted deterministic tools and visible evidence traces."],
          ["Safety", "No broker-password automation or trade execution is available."]
        ].map(([title, body]) => (
          <div key={title} className="rounded-lg border border-line bg-white p-5">
            <h2 className="text-base font-semibold text-ink">{title}</h2>
            <p className="mt-2 text-sm leading-6 text-muted">{body}</p>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        <Link className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white" href="/portfolios">
          Open portfolios
        </Link>
        <Link className="w-fit rounded-md border border-line bg-white px-4 py-2 text-sm font-semibold text-ink" href="/assistant">
          Open assistant
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
