**We’ve built much of the foundation. The biggest missing piece in this proposal is turning that data into compact, reusable company intelligence—so the assistant doesn’t rebuild the analysis through lots of tool calls every time.**

| Overarching step | What we already have | What needs improvement |
|---|---|---|
| **1. Collect reliable data** | DPS prices, benchmark history, financial reports/facts, macro series and filtered live news. | Finish coverage gaps, recurring price updates, shares/market cap, remaining corporate actions and searchable reports. |
| **2. Turn articles into reusable facts** | Clean article text, searchable passages, company/sector/topic tags and event grouping. | Extract source-backed event facts; distinguish reported facts, management claims and interpretation. **Searchable articles aren’t yet the complete fact layer described here.** |
| **3. Assemble a compact company snapshot** | Company research pages, saved exposure profiles/event briefs and numerical analytics. | Combine these into one consistent, comparison-ready view: financial trends, valuation, price behaviour, material events and missing-data flags. Existing saved briefs are only part of this. |
| **4. Keep briefs updated efficiently** | Cached research outputs and background-generation machinery. | Refresh affected briefs when meaningful information changes; reuse unchanged analysis. Continuous news ingestion does **not** yet mean continuously refreshed company briefs. |
| **5. Give chat the right evidence efficiently** | Database tools, bounded retrieval, company/portfolio context, citations and compacted tool results. | Reduce overlapping evidence and repeated retrieval. Give common questions a useful initial evidence pack while allowing the model to investigate further. |
| **6. Make research financially meaningful** | Financial comparisons, portfolio returns, concentration, covariance, risk contributions, benchmark comparison and allocation checks. | Improve comparable periods, corporate-action coverage, liquidity analysis and sector-specific measures. Historical returns alone don’t establish a credible long-term expected return. |
| **7. Produce clear, trustworthy answers** | Persistent streaming chat, saved conversations, source links and deterministic allocation verification. | Test whether answers actually resolve the user’s question, explain constraints clearly and distinguish a feasible candidate from a fully verified recommendation. |

**My recommended order:**

1. **Finish the essential data gaps**, rather than expanding sources indiscriminately.
2. **Build the article-to-facts layer** using the news we’re already collecting.
3. **Assemble compact company snapshots and comparisons.**
4. **Refresh cached briefs from meaningful changes.**
5. **Connect those snapshots to chat**, then measure answer quality, tokens and latency.
6. **Add missing sector and portfolio analysis** where the underlying data supports it.

I **wouldn’t adopt the entire router → planner → synthesizer → validator model chain** from this document by default. That adds calls and latency, and conflicts with your agreed model-led tool selection. The valuable parts are compact evidence, reusable analysis and reliable numerical verification. We already have the verification foundation; we need to improve what feeds it.

Add tavily search + GLM.