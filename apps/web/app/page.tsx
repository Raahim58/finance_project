import Link from "next/link";
import { Icon, type IconName } from "@/components/Icon";

const workspaces: Array<{ title: string; icon: IconName; description: string }> = [
  { title: "Today", icon: "grid", description: "Market conditions, portfolio performance, material events and data freshness in one view." },
  { title: "Markets", icon: "market", description: "Browse PSX companies, sectors, price history and technical charts." },
  { title: "Portfolios", icon: "briefcase", description: "Track holdings and cash. Set a portfolio IPS, compare allocations, and examine risk and scenarios." },
  { title: "Research", icon: "document", description: "Read stored reports and events, upload documents, and find passages with source and page references." },
  { title: "Monitoring", icon: "bell", description: "Review alerts, monitoring rules and saved recommendations before taking action." },
  { title: "Assistant", icon: "assistant", description: "Ask questions with company or portfolio context and review the evidence behind the answer." },
];

export default function HomePage() {
  return <main className="min-h-screen bg-[var(--canvas)]">
    <header className="mx-auto flex h-[74px] max-w-[1440px] items-center justify-between gap-4 px-5 sm:px-8 lg:px-12">
      <Link href="/" className="flex items-center gap-3" aria-label="RAAHIM home">
        <span className="brand-mark">R</span><span className="text-[13px] font-semibold">RAAHIM<span className="ml-2 hidden font-normal text-muted sm:inline">PSX portfolio workstation</span></span>
      </Link>
      <Link className="btn btn-primary whitespace-nowrap" href="/login">Sign in</Link>
    </header>
    <section className="mx-auto max-w-[1440px] px-5 pb-14 pt-14 sm:px-8 sm:pt-24 lg:px-12">
      <p className="eyebrow">PSX research · portfolio analysis</p>
      <h1 className="mt-5 max-w-5xl text-[40px] font-semibold leading-[1.04] tracking-[-.05em] text-ink sm:text-[64px] lg:text-[76px]">Research the market.<br/>Understand your portfolio.</h1>
      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <p className="max-w-2xl text-[16px] leading-7 text-muted">Follow PSX companies, manage portfolios, compare allocations and ask questions grounded in stored market data and original source documents.</p>
        <div className="flex flex-wrap items-start gap-3 lg:justify-end">
          <Link className="btn btn-primary min-h-11 px-5" href="/login">Open your workspace <Icon name="chevron" size={15}/></Link>
          <Link className="btn btn-secondary min-h-11 px-5" href="/dashboard">Explore demo</Link>
        </div>
      </div>
      <div className="mt-14 grid border-y border-line md:grid-cols-2">
        <section className="py-7 md:border-r md:border-line md:pr-8">
          <p className="metric-label">The market</p><h2 className="mt-3 text-xl font-semibold">Prices, companies and source evidence</h2>
          <p className="mt-3 max-w-xl text-sm leading-6 text-muted">Compare market and sector data, inspect company charts, and read reports and events with their sources and dates.</p>
        </section>
        <section className="border-t border-line py-7 md:border-t-0 md:pl-8">
          <p className="metric-label">Your portfolio</p><h2 className="mt-3 text-xl font-semibold">Holdings, objectives and decisions</h2>
          <p className="mt-3 max-w-xl text-sm leading-6 text-muted">Each portfolio has its own Investment Policy Statement. Review its valuation, performance, allocation proposals and modeled scenarios together.</p>
        </section>
      </div>
      <div className="mt-10 grid gap-x-10 gap-y-8 sm:grid-cols-2 lg:grid-cols-3">
        {workspaces.map(workspace=><section key={workspace.title}><div className="flex items-center gap-3"><Icon name={workspace.icon} size={19}/><h2 className="text-[15px] font-semibold">{workspace.title}</h2></div><p className="mt-3 text-[13px] leading-6 text-muted">{workspace.description}</p></section>)}
      </div>
    </section>
    <footer className="mx-auto flex max-w-[1440px] flex-wrap justify-between gap-4 border-t border-line px-5 py-6 text-xs leading-5 text-muted sm:px-8 lg:px-12">
      <p>Decision support only. The application does not place trades.</p><p>Sources, freshness and missing data remain part of the analysis.</p>
    </footer>
  </main>;
}
