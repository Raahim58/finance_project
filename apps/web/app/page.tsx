import Link from "next/link";
import { Icon } from "@/components/Icon";

const capabilities = [
  ["Portfolio construction", "Build and compare allocations against a confirmed mandate."],
  ["Risk and scenarios", "Trace concentration, tail risk, stress impact and constraint breaches."],
  ["Cited research", "Keep document evidence distinct from exact database values."],
];

export default function HomePage() {
  return (
    <main className="min-h-screen bg-[#f7f7f4]">
      <header className="mx-auto flex h-[74px] max-w-[1440px] items-center justify-between px-5 sm:px-8 lg:px-12">
        <Link href="/" className="flex items-center gap-3" aria-label="PSX Workstation home">
          <span className="brand-mark">PX</span>
          <span className="hidden sm:block"><strong className="block text-[13px] font-semibold tracking-[-.01em]">PSX Workstation</strong><span className="block text-[11px] text-muted">Evidence-led investing</span></span>
        </Link>
        <div className="flex items-center gap-2">
          <span className="hidden sm:inline"><Link className="btn btn-quiet" href="/dashboard">Open sample</Link></span>
          <Link className="btn btn-primary whitespace-nowrap px-3 sm:px-4" href="/dashboard">Build your mandate</Link>
        </div>
      </header>

      <section className="mx-auto max-w-[1440px] px-5 pb-16 pt-16 sm:px-8 sm:pt-24 lg:px-12">
        <div className="grid items-end gap-12 lg:grid-cols-[minmax(0,1fr)_380px]">
          <div>
            <p className="eyebrow">Portfolio intelligence for PSX investors</p>
            <h1 className="mt-5 max-w-4xl text-[46px] font-semibold leading-[.98] tracking-[-.055em] text-ink sm:text-[66px] lg:text-[78px]">Investment decisions,<br/>grounded in evidence.</h1>
          </div>
          <div className="border-l-2 border-accent pl-6">
            <p className="max-w-sm text-[15px] leading-7 text-muted">Portfolio construction, risk, stress testing and cited research—organized around your mandate, with source and freshness visible.</p>
            <div className="mt-7 flex flex-wrap gap-2">
              <Link className="btn btn-primary min-h-11 px-5" href="/dashboard">Build your portfolio <Icon name="chevron" size={15}/></Link>
              <Link className="btn btn-secondary min-h-11 px-5" href="/dashboard">Open workstation</Link>
            </div>
          </div>
        </div>

        <div className="mt-16 overflow-hidden rounded-[14px] border border-line bg-white shadow-[0_20px_70px_rgba(0,0,0,.055)]">
          <div className="grid min-h-[520px] lg:grid-cols-[210px_1fr]">
            <aside className="hidden border-r border-line bg-[#fbfbf8] p-4 lg:block" aria-hidden="true">
              <div className="mb-9 flex items-center gap-3 px-1"><span className="brand-mark">PX</span><span className="text-xs font-semibold">PSX Workstation</span></div>
              {[["Workspace","grid"],["Portfolios","briefcase"],["Markets","market"],["Research","search"],["Monitoring","bell"]].map(([label,icon],index)=><div key={label} className={`mb-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-xs font-semibold ${index===1?"bg-[#e8f3ee] text-accent":"text-muted"}`}><Icon name={icon as "grid"} size={16}/>{label}</div>)}
              <div className="mt-28 rounded-lg bg-surface p-3 text-[10px] leading-4 text-muted"><strong className="block text-ink">Decision support only</strong>No trade execution</div>
            </aside>
            <div className="min-w-0 bg-[#f7f7f4]">
              <div className="flex h-12 items-center justify-between border-b border-line px-5 text-[10px] text-muted"><span className="font-semibold text-ink">Portfolio workspace</span><span className="flex items-center gap-2"><i className="h-1.5 w-1.5 rounded-full bg-accent"/>Source and freshness labels active</span></div>
              <div className="p-5 sm:p-7">
                <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
                  <div><p className="eyebrow">Core portfolio</p><h2 className="mt-1 text-[28px] font-semibold tracking-[-.035em]">Mandate overview</h2><p className="mt-1 text-xs text-muted">Performance, allocation, risk and governing constraints</p></div>
                  <span className="badge badge-good">Within mandate</span>
                </div>
                <div className="mt-7 grid gap-5 sm:grid-cols-3">
                  <PreviewMetric label="Portfolio value" value="Database valuation" />
                  <PreviewMetric label="Performance" value="Ledger history" />
                  <PreviewMetric label="Objective" value="Confirmed IPS" />
                </div>
                <div className="mt-6 grid gap-4 xl:grid-cols-[1.65fr_1fr]">
                  <section className="rounded-xl border border-line bg-white p-5">
                    <div className="flex items-center justify-between"><strong className="text-xs">Portfolio trajectory</strong><span className="text-[10px] text-muted">Cumulative return</span></div>
                    <div className="mt-5 flex h-48 items-center justify-center rounded-lg bg-[#fafaf8]">
                      <svg className="h-full w-full" viewBox="0 0 620 190" role="img" aria-label="Workstation chart interface preview without sample financial values">
                        {[35,75,115,155].map(y=><line key={y} x1="30" x2="600" y1={y} y2={y} stroke="rgba(23,26,29,.065)"/>) }
                        <path d="M30 145 C95 138, 108 118, 158 127 S250 92, 302 103 S381 73, 432 82 S526 47, 600 55" fill="none" stroke="#126b52" strokeWidth="3" strokeLinecap="round"/>
                        <path d="M30 145 C95 138, 108 118, 158 127 S250 92, 302 103 S381 73, 432 82 S526 47, 600 55 L600 170 L30 170 Z" fill="rgba(18,107,82,.055)"/>
                      </svg>
                    </div>
                  </section>
                  <section className="rounded-xl border border-line bg-white p-5">
                    <div className="flex items-center justify-between"><strong className="text-xs">Decision context</strong><span className="text-[10px] text-muted">Auditable</span></div>
                    <div className="mt-5 space-y-4">{["Mandate compliance","Risk contribution","Evidence coverage","Data freshness"].map((label,index)=><div key={label}><div className="mb-1.5 flex justify-between text-[10px]"><span className="text-muted">{label}</span><span className="font-semibold">{index===0?"Checked":"Visible"}</span></div><div className="h-1.5 rounded-full bg-surface"><div className="h-full rounded-full bg-accent" style={{width:`${88-index*13}%`,opacity:1-index*.12}}/></div></div>)}</div>
                  </section>
                </div>
                <p className="mt-4 text-right text-[10px] text-muted">Interface preview · no sample financial values</p>
              </div>
            </div>
          </div>
        </div>

        <div className="grid border-t border-line md:grid-cols-3">
          {capabilities.map(([title, text], index) => <article key={title} className="py-8 md:px-7 md:first:pl-0 md:last:pr-0"><div className="mb-5 flex items-center gap-3"><span className="data-font text-[11px] text-muted">0{index+1}</span><span className="h-px flex-1 bg-line"/></div><h2 className="text-[16px] font-semibold">{title}</h2><p className="mt-2 max-w-sm text-[13px] leading-6 text-muted">{text}</p></article>)}
        </div>
      </section>

      <footer className="border-t border-line px-5 py-6 text-center text-[11px] text-muted">PSX Workstation provides analysis and decision support. It does not place trades.</footer>
    </main>
  );
}

function PreviewMetric({label,value}:{label:string;value:string}) {
  return <div><p className="metric-label">{label}</p><p className="mt-2 text-[17px] font-semibold tracking-[-.02em]">{value}</p></div>;
}
