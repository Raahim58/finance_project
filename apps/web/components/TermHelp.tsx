"use client";

const definitions: Record<string, string> = {
  "Annual volatility": "How widely returns varied, annualized from the available daily price history. Higher values mean a less stable return path.",
  "Historical VaR 95": "The loss threshold exceeded on roughly 5% of observed days. It is historical, not a worst-case loss forecast.",
  "Historical ES 95": "The average loss on observed days that were worse than the 95% VaR threshold.",
  "Sharpe ratio": "Expected excess return per unit of modeled volatility. It depends on the recorded expected-return and risk-free-rate assumptions.",
  "Portfolio beta": "Estimated sensitivity of portfolio returns to the selected market benchmark. A beta of 1 implies similar movement on average.",
  "Concentration HHI": "A concentration index formed from squared portfolio weights. Higher values indicate that capital is held in fewer, larger positions.",
  "Risk contribution": "The position's modeled share of total risky-asset variance, including how it moves with other holdings.",
  "Average holding correlation": "The average tendency of this security's returns to move with current holdings. Lower is usually more diversifying, but does not guarantee lower portfolio risk.",
  "Sector headroom": "How much additional sector weight remains before reaching the confirmed IPS sector limit.",
  "Position headroom": "How much additional security weight remains before reaching the confirmed IPS position limit.",
  "IPS": "Investment Policy Statement: the confirmed objectives and constraints the portfolio is evaluated against.",
  "Macro regime": "A rule-based summary of selected rates, currency, inflation, oil and market-breadth observations. It routes scenarios; it is not a forecast.",
  "Expected return": "A deterministic estimate based on the recorded return model and assumptions, not an AI forecast or guaranteed outcome.",
};

export function TermHelp({ term, definition }: { term: string; definition?: string }) {
  const text = definition ?? definitions[term];
  if (!text) return null;
  const id = `term-${term.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return <span className="term-help">
    <button type="button" className="term-help-trigger" aria-label={`Explain ${term}`} aria-describedby={id}>?</button>
    <span className="term-help-popover" id={id} role="tooltip"><strong>{term}</strong>{text}</span>
  </span>;
}

export function TermLabel({ term, children }: { term: string; children?: React.ReactNode }) {
  return <span className="inline-flex items-center gap-1">{children ?? term}<TermHelp term={term} /></span>;
}
