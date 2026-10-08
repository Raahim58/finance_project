import type { TechnicalBar } from "@/lib/technical/types";
export const escapeHtml = (text: string) => text.replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]!));
export function technicalTooltip(bar: TechnicalBar, values: Array<[
    string,
    number | null
]> = [], events: string[] = []) {
    const format = (value: number | null) => value == null ? "—" : new Intl.NumberFormat("en-PK", { maximumFractionDigits: 2 }).format(value);
    const rows: Array<[
        string,
        string
    ]> = [["Open", format(bar.open)], ["High", format(bar.high)], ["Low", format(bar.low)], ["Close", format(bar.close)], ["Change", bar.changePercent == null ? "—" : `${format(bar.changePercent)}%`], ["Volume", format(bar.volume)], ...values.map(([name, value]): [
            string,
            string
        ] => [name, format(value)])];
    return `<div style="max-width:230px;font-size:11px;line-height:1.5"><b>${escapeHtml(bar.date)}</b>${rows.map(([name, value]) => `<div style="display:flex;justify-content:space-between;gap:18px"><span>${escapeHtml(name)}</span><b>${escapeHtml(value)}</b></div>`).join("")}${events.map(event => `<div style="margin-top:5px">${escapeHtml(event)}</div>`).join("")}</div>`;
}
