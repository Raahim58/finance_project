import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "PSX AI Portfolio Agent",
  description: "Portfolio intelligence assistant for Pakistan Stock Exchange investors"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-line bg-white">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
            <Link href="/" className="text-base font-semibold text-ink">
              PSX Quant Workstation
            </Link>
            <nav className="flex gap-4 text-sm text-muted">
              <Link href="/dashboard">Dashboard</Link>
              <Link href="/portfolios">Portfolios</Link>
              <Link href="/markets">Markets</Link>
              <Link href="/research">Research</Link>
              <Link href="/assistant">Assistant</Link>
              <Link href="/settings">Settings</Link>
              <Link href="/login">Login</Link>
            </nav>
          </div>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
