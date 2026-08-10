import Link from "next/link";

export default function HomePage() {
  return (
    <section className="mx-auto grid min-h-[calc(100vh-64px)] max-w-6xl content-center gap-8 px-5 py-12 md:grid-cols-[1.1fr_0.9fr]">
      <div>
        <p className="mb-3 text-sm font-medium uppercase tracking-wide text-accent">Quant workstation</p>
        <h1 className="max-w-3xl text-4xl font-semibold leading-tight text-ink md:text-5xl">
          PSX portfolio intelligence with cited AI analysis.
        </h1>
        <p className="mt-5 max-w-2xl text-base leading-7 text-muted">
          Build independent portfolios, maintain an auditable cash and transaction ledger, compare
          deterministic risk and optimizer proposals, research cited evidence, and stress-test your
          holdings without placing trades.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white" href="/signup">
            Create account
          </Link>
          <Link className="rounded-md border border-line bg-white px-4 py-2 text-sm font-semibold text-ink" href="/login">
            Login
          </Link>
        </div>
      </div>
      <div className="grid content-start gap-3 rounded-lg border border-line bg-white p-5">
        {[
          "Ledger-derived positions, cash, valuation, and P&L",
          "Reproducible quant, risk, optimization, and scenarios",
          "Structured facts separated from cited document retrieval",
          "Grounded assistant tools with freshness and ownership controls"
        ].map((item) => (
          <div key={item} className="rounded-md border border-line bg-surface px-4 py-3 text-sm text-ink">
            {item}
          </div>
        ))}
      </div>
    </section>
  );
}
