"use client";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { clearApiCache, getPortfolios, selectDefaultPortfolio, type Portfolio } from "@/lib/api";

export function PortfolioContextPicker() {
  const path = usePathname();
  const router = useRouter();
  const [rows, setRows] = useState<Portfolio[]>([]), [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void getPortfolios().then(portfolios => {
      if (!active) return;
      setRows(portfolios.filter(row => !row.archived_at));
      setSelected(portfolios.find(row => row.is_default && !row.archived_at)?.id ?? "");
    }).catch(() => { if (active) setError("Portfolio context unavailable"); });
    return () => { active = false; };
  }, [path]);
  async function choose(id: string) {
    if (!id || id === selected) return;
    setBusy(true); setError("");
    try {
      await selectDefaultPortfolio(id); clearApiCache(); setSelected(id); window.dispatchEvent(new Event("psx-portfolio-change"));
      const tab = path.match(/^\/portfolios\/[^/]+\/(overview|ips|build|quant|risk|scenarios|research|activity)$/)?.[1];
      if (tab) router.push(`/portfolios/${encodeURIComponent(id)}/${tab}` as never);
    }
    catch { setError("Portfolio could not be selected"); }
    finally { setBusy(false); }
  }
  return <div className="portfolio-context">
    <select aria-label="Selected portfolio context" value={selected} disabled={busy || !rows.length} onChange={event => void choose(event.target.value)}>
      <option value="">{error || "Select portfolio"}</option>{rows.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
    </select>{error && rows.length ? <span role="alert">{error}</span> : null}
  </div>;
}
