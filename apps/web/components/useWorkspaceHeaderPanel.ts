"use client";

import { useEffect } from "react";

/** Align the fixed header with the real responsive width of the left column. */
export function useWorkspaceHeaderPanel(pathname: string) {
  useEffect(() => {
    const shell = document.querySelector<HTMLElement>(".workstation-shell");
    if (!shell) return;
    let panel: HTMLElement | null = null;
    let frame = 0;
    const update = () => {
      const next = document.querySelector<HTMLElement>("[data-workspace-left-panel]");
      if (next !== panel) {
        if (panel) { resize.unobserve(panel); delete panel.dataset.headerRaised; }
        panel = next;
        if (panel) resize.observe(panel);
      }
      const bounds = panel?.getBoundingClientRect();
      const sibling = panel?.nextElementSibling?.getBoundingClientRect();
      // Stacked mobile panels must stay below the full-width mobile header.
      const raised = window.innerWidth > 720 && bounds && sibling && sibling.x >= bounds.right - 1;
      if (panel) panel.dataset.headerRaised = raised ? "true" : "false";
      shell.style.setProperty("--workspace-left-width", raised ? `${bounds.width}px` : "0px");
    };
    const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(update); };
    const resize = new ResizeObserver(schedule);
    const mutation = new MutationObserver(schedule);
    mutation.observe(document.body, { childList: true, subtree: true });
    window.addEventListener("resize", schedule);
    update();
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect(); mutation.disconnect();
      window.removeEventListener("resize", schedule);
      if (panel) delete panel.dataset.headerRaised;
      shell.style.removeProperty("--workspace-left-width");
    };
  }, [pathname]);
}
