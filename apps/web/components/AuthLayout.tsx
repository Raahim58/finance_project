import Link from "next/link";

export function AuthLayout({ title, description, children, footer, legal }: {
  title: string;
  description: string;
  children: React.ReactNode;
  footer: React.ReactNode;
  legal?: string;
}) {
  return (
    <div className="rx rx-auth">
      <header className="rx-auth-head">
        <Link href="/" className="rx-auth-mark" aria-label="RAAHIM home">R</Link>
        <span className="rx-auth-brand">RAAHIM</span>
      </header>
      <main className="rx-auth-main">
        <div className="rx-auth-card">
          <div>
            <h1 className="rx-title">{title}</h1>
            <p className="rx-sub">{description}</p>
          </div>
          {children}
          <div className="rx-auth-foot">{footer}</div>
        </div>
      </main>
      {legal ? <p className="rx-auth-legal">{legal}</p> : null}
    </div>
  );
}
