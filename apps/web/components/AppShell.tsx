"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, IconName } from "@/components/Icon";

const primary: Array<[string,string,IconName]> = [
  ["Workspace","/dashboard","grid"],["Portfolios","/portfolios","briefcase"],["Markets","/markets","market"],
  ["Research","/research","search"],["Assistant","/assistant","assistant"]
];
const oversight: Array<[string,string,IconName]> = [
  ["Recommendations","/recommendations","lightbulb"],["Monitoring","/monitoring","bell"],["Activity","/activity","activity"]
];

function NavItem({item}:{item:[string,string,IconName]}) {
  const pathname=usePathname(); const [label,href,icon]=item;
  const active=pathname===href || (href!=="/dashboard" && pathname.startsWith(href)) || (href==="/markets" && pathname.startsWith("/market"));
  return <Link href={href as never} aria-current={active?"page":undefined} title={label} className={`flex min-h-9 items-center gap-3 border-l-2 px-4 text-[12px] font-medium transition-colors lg:px-5 ${active?"border-[#63b59a] bg-white/10 text-white":"border-transparent text-[#b8c7d3] hover:bg-white/[.06] hover:text-white"}`}><Icon name={icon} size={16}/><span className="sidebar-label">{label}</span></Link>;
}

export function AppShell({children}:{children:React.ReactNode}) {
  const pathname=usePathname();
  const auth=pathname==="/"||pathname==="/login"||pathname==="/signup"||pathname==="/onboarding";
  if(auth) return <>{children}</>;
  return <div className="app-shell">
    <aside className="app-sidebar" aria-label="Primary navigation">
      <Link href="/dashboard" className="flex h-[62px] w-full items-center gap-3 border-b border-white/10 px-4 lg:px-5">
        <span className="grid h-7 w-7 shrink-0 place-items-center border border-[#7ba5c5] text-[11px] font-bold tracking-tight text-white">PX</span>
        <span className="sidebar-wordmark"><strong className="block text-[12px] tracking-wide text-white">PSX WORKSTATION</strong><span className="text-[9px] uppercase tracking-[.14em] text-[#91a9bb]">Portfolio intelligence</span></span>
      </Link>
      <div className="flex-1 overflow-y-auto py-4 max-md:flex max-md:w-full max-md:items-center max-md:overflow-x-auto max-md:py-0">
        <p className="sidebar-section mb-2 px-5 text-[9px] font-bold uppercase tracking-[.16em] text-[#718da3]">Investment</p>
        {primary.map(item=><NavItem key={item[1]} item={item}/>)}
        <p className="sidebar-section mb-2 mt-6 px-5 text-[9px] font-bold uppercase tracking-[.16em] text-[#718da3]">Oversight</p>
        {oversight.map(item=><NavItem key={item[1]} item={item}/>)}
        <p className="sidebar-section mb-2 mt-6 px-5 text-[9px] font-bold uppercase tracking-[.16em] text-[#718da3]">System</p>
        <NavItem item={["Settings","/settings","settings"]}/>
      </div>
      <div className="sidebar-footer-copy border-t border-white/10 p-4 text-[10px] leading-4 text-[#91a9bb]">Decision support only<br/>No trade execution</div>
    </aside>
    <div className="app-main">
      <header className="app-topbar">
        <div className="flex min-w-0 items-center gap-3 text-[11px]"><span className="badge">Evidence mode</span><span className="desktop-only text-muted">Market data is source and freshness labeled</span></div>
        <div className="flex items-center gap-1"><Link className="icon-btn" title="Monitoring" aria-label="Open monitoring" href={"/monitoring" as never}><Icon name="bell"/></Link><span className="ml-1 hidden border-l border-line pl-3 text-[11px] font-semibold sm:block">Institutional desk</span></div>
      </header>
      <main>{children}</main>
    </div>
  </div>;
}
