"use client";

import Link from "next/link";
import { AssistantWorkspaceProvider, useAssistantWorkspace } from "@/components/AssistantWorkspace";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Icon, IconName } from "@/components/Icon";
import { PortfolioContextPicker } from "@/components/PortfolioContextPicker";

type NavEntry = [string, string, IconName];

const groups: Array<{ label: string; items: NavEntry[] }> = [
  { label: "Workspace", items: [["Today", "/dashboard", "grid"]] },
  { label: "Investment", items: [
    ["Markets", "/markets", "market"],
    ["Portfolios", "/portfolios", "briefcase"],
    ["Research", "/research", "document"],
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
      <span className="rail-icon"><Icon name={icon} size={20} /></span>
      <span className="sidebar-label">{label}</span>
    </Link>
  );
}

function ChatNavigation() {
  const workspace = useAssistantWorkspace();
  return <button className="nav-item" onClick={() => workspace?.open()}><span className="rail-icon"><Icon name="assistant" size={20} /></span><span className="sidebar-label">Chat</span></button>;
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

function MobileNavDrawer({ pathname, onClose }: { pathname: string; onClose: () => void }) {
  const drawerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const drawer = drawerRef.current;
    const focusable = drawer ? Array.from(drawer.querySelectorAll<HTMLElement>('a[href], button:not([disabled])')) : [];
    focusable[0]?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") { onClose(); return; }
      if (event.key !== "Tab" || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="mobile-nav-overlay">
      <button type="button" className="mobile-nav-backdrop" aria-label="Close primary navigation" onClick={onClose} />
      <div className="mobile-nav-drawer" id="mobile-nav-drawer" role="dialog" aria-modal="true" aria-label="Primary navigation" ref={drawerRef}>
        <div className="flex items-center justify-between px-5 py-4">
          <span className="text-[13px] font-semibold">PSX Workstation</span>
          <button type="button" className="icon-btn" aria-label="Close primary navigation" onClick={onClose}><Icon name="close" /></button>
        </div>
        <nav className="flex-1 overflow-y-auto pb-5" aria-label="Primary navigation links">
          {groups.map(group => (
            <div key={group.label}>
              <p className="nav-section">{group.label}</p>
              {group.items.map(([label, href, icon]) => (
                <Link key={href} href={href as never} aria-current={isActive(pathname, href) ? "page" : undefined} className="nav-item" onClick={onClose}>
                  <Icon name={icon} size={17} />
                  <span>{label}</span>
                </Link>
              ))}
            </div>
          ))}
        </nav>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const publicRoute = pathname === "/" || pathname === "/login" || pathname === "/signup" || pathname === "/onboarding";
  const [menuOpen, setMenuOpen] = useState(false);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { setMenuOpen(false); }, [pathname]);
  const closeMenu = () => { setMenuOpen(false); menuTriggerRef.current?.focus(); };
  if (publicRoute) return <>{children}</>;

  return (
    <AssistantWorkspaceProvider><div className="app-shell workstation-shell" data-workspace={pathname === "/market" || pathname === "/markets" ? "markets" : "default"}>
      <aside className="app-sidebar" aria-label="Primary navigation">
        <Link href="/dashboard" className="workstation-brand" aria-label="RAAHIM home">R</Link>
        <nav className="rail-navigation" aria-label="Workspace navigation">
          {groups.filter(group => group.label !== "System").map(group => (
            <div key={group.label}>
              {group.items.filter(([label]) => !["Recommendations", "Activity"].includes(label)).map(item => <NavItem key={item[1]} item={item} pathname={pathname} />)}
            </div>
          ))}
          <ChatNavigation />
          <details className="rail-more"><summary className="nav-item"><span className="rail-icon"><Icon name="more" size={20} /></span><span className="sidebar-label">More</span></summary><nav aria-label="More workspace pages" className="rail-more-menu">
            {groups.flatMap(group => group.items).filter(([label]) => ["Recommendations", "Activity"].includes(label)).map(item => <NavItem key={item[1]} item={item} pathname={pathname} />)}
          </nav></details>
        </nav>
        <div className="rail-bottom"><NavItem item={["Settings", "/settings", "settings"]} pathname={pathname} /></div>
      </aside>
      <div className="app-main">
        <header className="app-topbar">
          <div className="flex min-w-0 items-center gap-3">
            <button type="button" ref={menuTriggerRef} className="mobile-menu-btn icon-btn" aria-label="Open primary navigation" aria-haspopup="dialog" aria-expanded={menuOpen} aria-controls="mobile-nav-drawer" onClick={() => setMenuOpen(true)}>
              <Icon name="menu" />
            </button>
            <span className="truncate text-[12px] font-semibold text-ink">{currentScope(pathname)}</span>
          </div>
          <div className="flex items-center gap-1">
            <PortfolioContextPicker />
            <Link className="icon-btn" title="Search evidence" aria-label="Search evidence" href={"/research" as never}><Icon name="search" /></Link>
            <Link className="icon-btn" title="Open monitoring" aria-label="Open monitoring" href={"/monitoring" as never}><Icon name="bell" /></Link>
            <Link className="icon-btn" aria-label="Account settings" href={"/settings" as never}><Icon name="settings" /></Link>
          </div>
        </header>
        <main>{children}</main>
      </div>
      {menuOpen ? <MobileNavDrawer pathname={pathname} onClose={closeMenu} /> : null}
    </div></AssistantWorkspaceProvider>
  );
}
