"use client";

import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Keep data warnings in the analytical column, so they cannot lower the left panel. */
export function WorkspaceDataNotices({ ready, scope, children }: { ready: boolean; scope: string; children: ReactNode }) {
  const [target, setTarget] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!ready) { setTarget(null); return; }
    const update = () => {
      const next = document.querySelector<HTMLElement>("[data-portfolio-panel='content']");
      setTarget(previous => previous === next ? previous : next);
    };
    const observer = new MutationObserver(update);
    observer.observe(document.body, { childList: true, subtree: true });
    update();
    return () => observer.disconnect();
  }, [ready, scope]);
  if (!children) return null;
  const notices = <div className="workspace-data-notices">{children}</div>;
  return target?.isConnected ? createPortal(notices, target) : notices;
}
