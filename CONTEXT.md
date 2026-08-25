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
A portfolio-specific assessment of whether a security fits one selected portfolio and its confirmed IPS. It requires an explicitly selected portfolio.
_Avoid_: Company Intelligence
