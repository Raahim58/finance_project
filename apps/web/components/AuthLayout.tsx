import Link from "next/link";

export function AuthLayout({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <main className="grid min-h-screen bg-white lg:grid-cols-[minmax(0,1fr)_440px]">
      <section className="flex min-h-screen flex-col px-5 py-6 sm:px-10 lg:px-16 lg:py-10">
        <Link href="/" className="flex w-max items-center gap-3" aria-label="Back to PSX Workstation home">
          <span className="brand-mark">PX</span>
          <span><strong className="block text-[13px] font-semibold">PSX Workstation</strong><span className="block text-[11px] text-muted">Evidence-led investing</span></span>
        </Link>
        <div className="mx-auto my-auto w-full max-w-[430px] py-16">
          <p className="eyebrow">Private investment workspace</p>
          <h1 className="mt-3 text-[36px] font-semibold leading-tight tracking-[-.04em]">{title}</h1>
          <p className="mt-3 text-sm leading-6 text-muted">{description}</p>
          <div className="mt-8">{children}</div>
          <div className="mt-5 text-sm text-muted">{footer}</div>
        </div>
        <p className="text-[11px] text-muted">Analysis only · No automated trading</p>
      </section>
      <aside className="hidden bg-[#f1f2ef] px-12 py-14 lg:flex lg:flex-col lg:justify-between">
        <div>
          <p className="eyebrow">Workstation principles</p>
          <p className="mt-5 text-[26px] font-medium leading-[1.25] tracking-[-.035em]">The number, the source, and the decision context stay together.</p>
        </div>
        <div className="space-y-7">
          <AuthPoint label="Structured values" text="Portfolio and market numbers come from database queries." />
          <AuthPoint label="Cited narrative" text="Document research retains source and page metadata." />
          <AuthPoint label="Explicit uncertainty" text="Missing, stale, or unsupported data remains visible." />
        </div>
      </aside>
    </main>
  );
}

function AuthPoint({label,text}:{label:string;text:string}) {
  return <div className="border-l-2 border-accent pl-4"><h2 className="text-[13px] font-semibold">{label}</h2><p className="mt-1 text-[12px] leading-5 text-muted">{text}</p></div>;
}
