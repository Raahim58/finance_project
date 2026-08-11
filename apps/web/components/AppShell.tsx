"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, IconName } from "@/components/Icon";

type NavEntry = [string, string, IconName];

const groups: Array<{ label: string; items: NavEntry[] }> = [
  { label: "Workspace", items: [["Overview", "/dashboard", "grid"]] },
  { label: "Investment", items: [
    ["Portfolios", "/portfolios", "briefcase"],
    ["Markets", "/markets", "market"],
    ["Research", "/research", "search"],
    ["Assistant", "/assistant", "assistant"],
  ] },
  { label: "Oversight", items: [
    ["Recommendations", "/recommendations", "lightbulb"],
    ["Monitoring", "/monitoring", "bell"],
    ["Activity", "/activity", "activity"],
  ] },
  { label: "System", items: [["Settings", "/settings", "settings"]] },
];

function isActive(pathname: string, href: string) {
  return pathname === href
    || (href !== "/dashboard" && pathname.startsWith(href))
    || (href === "/markets" && (pathname.startsWith("/market") || pathname.startsWith("/companies")));
}

function NavItem({ item, pathname }: { item: NavEntry; pathname: string }) {
  const [label, href, icon] = item;
  const active = isActive(pathname, href);
  return (
    <Link href={href as never} aria-current={active ? "page" : undefined} title={label} className="nav-item">
      <Icon name={icon} size={17} />
      <span className="sidebar-label">{label}</span>
    </Link>
  );
}

function currentScope(pathname: string) {
  if (pathname.startsWith("/portfolios/")) return "Portfolio workspace";
  if (pathname.startsWith("/companies/")) return "Security research";
  for (const group of groups) {
    const match = group.items.find(([, href]) => isActive(pathname, href));
    if (match) return match[0];
  }
  return "Investment workspace";
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const publicRoute = pathname === "/" || pathname === "/login" || pathname === "/signup" || pathname === "/onboarding";
  if (publicRoute) return <>{children}</>;

  return (
    <div className="app-shell">
      <aside className="app-sidebar" aria-label="Primary navigation">
        <Link href="/dashboard" className="flex h-[76px] w-full items-center gap-3 px-5 max-lg:justify-center max-lg:px-0">
          <span className="brand-mark">PX</span>
          <span className="sidebar-wordmark min-w-0">
            <strong className="block text-[13px] font-semibold tracking-[-.01em]">PSX Workstation</strong>
            <span className="block text-[11px] text-muted">Portfolio intelligence</span>
          </span>
        </Link>
        <div className="flex-1 overflow-y-auto pb-5 max-md:flex max-md:items-center max-md:overflow-x-auto max-md:pb-0">
          {groups.map(group => (
            <div key={group.label}>
              <p className="nav-section sidebar-section">{group.label}</p>
              {group.items.map(item => <NavItem key={item[1]} item={item} pathname={pathname} />)}
            </div>
          ))}
        </div>
        <div className="sidebar-footer-copy mx-4 mb-4 rounded-lg bg-surface p-3 text-[11px] leading-5 text-muted">
          <strong className="block font-semibold text-ink">Decision support only</strong>
          No broker connection or trade execution
        </div>
      </aside>
      <div className="app-main">
        <header className="app-topbar">
          <div className="flex min-w-0 items-center gap-3">
            <span className="truncate text-[12px] font-semibold text-ink">{currentScope(pathname)}</span>
            <span className="desktop-only h-4 w-px bg-line" />
            <span className="desktop-only flex items-center gap-2 text-[11px] text-muted">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" />
              Source and freshness labels active
            </span>
          </div>
          <div className="flex items-center gap-1">
            <Link className="icon-btn" title="Search evidence" aria-label="Search evidence" href={"/research" as never}><Icon name="search" /></Link>
            <Link className="icon-btn" title="Open monitoring" aria-label="Open monitoring" href={"/monitoring" as never}><Icon name="bell" /></Link>
            <Link className="ml-1 hidden h-8 items-center border-l border-line pl-4 text-[12px] font-semibold sm:flex" href={"/settings" as never}>Investor desk</Link>
          </div>
        </header>
        <main>{children}</main>
      </div>
    </div>
  );
}
