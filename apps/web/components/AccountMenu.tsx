"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { clearToken, getToken } from "@/lib/api/client";

/** Sign in / account control for the bottom of the rail. */
export function AccountMenu() {
  const router = useRouter();
  const [signedIn, setSignedIn] = useState(false);
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const sync = () => setSignedIn(Boolean(getToken()));
    sync();
    window.addEventListener("psx-auth-change", sync);
    window.addEventListener("storage", sync);
    return () => { window.removeEventListener("psx-auth-change", sync); window.removeEventListener("storage", sync); };
  }, []);
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", key); };
  }, [open]);
  if (!signedIn) {
    return <div className="account-menu"><Link href={"/login" as never} className="nav-item" title="Log in"><span className="rail-icon"><Icon name="company" size={20} /></span><span className="sidebar-label">Log in</span></Link></div>;
  }
  return (
    <div className="account-menu" ref={root}>
      <button type="button" className="nav-item" aria-haspopup="menu" aria-expanded={open} title="Account" onClick={() => setOpen(!open)}>
        <span className="rail-icon"><Icon name="company" size={20} /></span><span className="sidebar-label">Account</span>
      </button>
      {open ? <div className="account-menu-pop" role="menu">
        <Link role="menuitem" href={"/settings" as never} onClick={() => setOpen(false)}><Icon name="settings" size={15} />Settings</Link>
        <button role="menuitem" type="button" onClick={() => { clearToken(); setOpen(false); router.push("/login" as never); }}>Log out</button>
      </div> : null}
    </div>
  );
}
