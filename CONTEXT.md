# PSX Portfolio Intelligence

This context describes the portfolio-specific mandate and evidence used to produce grounded investment intelligence.

## Language

**Investment Policy Statement (IPS)**:
The confirmed, portfolio-specific record of the investor's objectives, risk capacity, risk willingness, risk tolerance, horizon, liquidity needs, benchmarks, preferences, exclusions, and binding constraints. It is the authoritative source of investment preferences for that portfolio.
_Avoid_: Global investor preferences, personal investment context

**Investment preference**:
An objective, tolerance, horizon, preference, or restriction recorded within a portfolio's confirmed IPS. It does not exist as an independent user-level input to portfolio intelligence.
_Avoid_: User preference, account preference

**Application preference**:
A user-level setting that controls application behavior without expressing an investment mandate, such as the selected LLM provider or notification behavior.
_Avoid_: Investment preference

**Company Intelligence**:
An assessment of a company using company facts, market and risk metrics, sector and macro context, relevant events, RAG evidence, and missing-data states. It is not portfolio-specific and contains neither a portfolio nor an IPS.
_Avoid_: Personalized company intelligence, Security Fit

**Portfolio Relevance**:
The relationship between a company and one selected portfolio, evaluated using that portfolio's holdings, risk, and confirmed IPS. It is included only when a portfolio is explicitly selected.
_Avoid_: Global investor relevance

**Security Fit**:
A portfolio-specific assessment of whether a security fits one resolved portfolio and its confirmed IPS. The portfolio may be explicitly selected or supplied by the Globally Selected Portfolio fallback.
_Avoid_: Company Intelligence

**Required Return**:
The portfolio return hurdle recorded in, or deterministically derived from, the confirmed IPS. It expresses what the investor requires; it is not a forecast of what a security or portfolio will earn.
_Avoid_: Expected return, promised return

**Modeled Expected Return**:
An explicitly labeled estimate produced from a documented quantitative method and observed inputs. It is distinct from the IPS Required Return and is unavailable when the method's required evidence is missing.
_Avoid_: IPS target, guaranteed return

**Globally Selected Portfolio**:
The one active, user-owned portfolio selected as the application-wide default. It is the Assistant's fallback portfolio context when the user does not explicitly identify a portfolio. Its identifier and name are supplied to the Assistant with the request; portfolio scope is not silently selected by parsing free-form text. If no Globally Selected Portfolio exists, portfolio-specific analysis is unavailable.
_Avoid_: Inferred portfolio, arbitrary first portfolio

**Return-Constrained Portfolio Analysis**:
A deterministic portfolio analysis in which the IPS Required Return is the target constraint and Modeled Expected Returns are the asset-level inputs used to test feasibility. The current default evidence basis is historical annualized returns shrunk toward the analyzed universe average; CAPM is an alternative only when its approved market proxy and effective-dated observed risk-free rate are available. Explicit asset-return assumptions must come from the user. The Assistant may explain existing analysis results but does not run or save this analysis in the current phase.
_Avoid_: Treating the IPS Required Return as an asset forecast, LLM-generated return assumptions

**Market-Sector Expected Return Model**:
A possible future Modeled Expected Return method that estimates security returns from market and sector factor exposures. It is a future research and validation candidate, not a dependency of the current return architecture or a capability the Assistant may imply is already available.
_Avoid_: Current expected-return method, unvalidated APT forecast

**Investment Recommendation**:
A non-executing, evidence-backed assessment produced in response to a user's request. It may state an explicit advisory conclusion such as Buy/Add, Hold, Reduce, or Avoid. Its portfolio context defaults to the Globally Selected Portfolio, while its security candidate universe follows the request: existing holdings, a user-named comparison set, or the wider eligible market universe. A materially relevant alternative outside a named comparison may be mentioned transparently, but no recommendation changes portfolio or IPS state.
_Avoid_: Trade instruction, autonomous action

**Market-Wide Candidate Discovery**:
A broad first-pass assessment in which every eligible active security is grouped by its authoritative available Security Classification and represented by compact structured evidence appropriate to that group. The Assistant evaluates securities primarily against their peers, selects bounded sector candidates for deeper Canonical Intelligence Context assembly, and only then performs portfolio-aware cross-sector comparison. It does not issue an Investment Recommendation during discovery. Unclassified securities remain visible as unclassified rather than being guessed or silently omitted.
_Avoid_: Final recommendation, preselected market-wide shortlist

**Security Classification**:
A sourced, reviewable assignment of a security to a market taxonomy. The current authoritative classification is the PSX sector observed from the PSX symbol universe. A sub-industry may be used only when a separately verified source supplies it; the Assistant never invents one from a company name or narrative.
_Avoid_: LLM-inferred sector, assumed sub-industry

**Peer Group Analysis**:
Comparison of a security with companies sharing the same authoritative available Security Classification, using consistent periods, units, definitions, and group-appropriate metrics. The current default peer group is the PSX sector. Data completeness and classification limitations remain explicit, and a raw metric is not treated as comparable across incompatible business models.
_Avoid_: Unqualified whole-market rank, cross-sector raw-metric comparison

**Recommendation Evidence Gate**:
The minimum evidence condition for issuing an explicit Investment Recommendation. Missing or stale core evidence requires an Insufficient Evidence result instead of an advisory label. Missing non-core evidence permits a clearly qualified Low Confidence recommendation that identifies the gaps. Portfolio-specific conclusions treat the selected portfolio and its confirmed IPS as core evidence.
_Avoid_: Guessing through core data gaps, hiding uncertainty

**Recommendation Synthesis Unavailable**:
A response state used when evidence may be available but the configured model cannot produce a valid recommendation answer. It returns the available deterministic factual summary and evidence without a Buy/Add, Hold, Reduce, or Avoid conclusion. It is distinct from Insufficient Evidence, which describes the evidence rather than the synthesis service.
_Avoid_: Insufficient Evidence, deterministic investment conclusion

**Recommendation Horizon**:
The timeframe over which an Investment Recommendation's advisory conclusion applies. It comes from the selected portfolio's confirmed IPS when available, otherwise from an explicit user request. When neither supplies a horizon, the Assistant does not silently choose one; it distinguishes relevant short-, medium-, and long-term views or requests a horizon before issuing one overall label.
_Avoid_: Timeless Buy/Hold/Reduce/Avoid label, assumed holding period

**Recommendation Rationale**:
The reviewable support for an explicit Investment Recommendation: advisory conclusion, Recommendation Horizon, core thesis, portfolio and IPS fit when applicable, supporting catalysts, principal risks, invalidation conditions, confidence, missing evidence, and citations for every material factual claim. It may be rendered conversationally, but none of these meanings may be silently omitted.
_Avoid_: Unsupported label, unqualified recommendation

**Reasoning Execution**:
A stateless evaluation of the current request using its Globally Selected Portfolio fallback, any explicitly selected security, bounded conversational context, and freshly assembled Canonical Intelligence Context. It produces a grounded result but does not own conversation threads, saved messages, long-term summaries, or resumption. Market-sensitive evidence is refreshed for each execution rather than inherited as truth from an earlier answer.
_Avoid_: Conversation Workspace, persistent assistant memory
