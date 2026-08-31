# Phase 6.5 — Deterministic Event Impact Engine

## Purpose

Phase 6 currently does the following correctly:

1. ingests and retains evidence;
2. normalizes raw evidence into `NormalizedEvent`;
3. classifies event type and primary factor;
4. links events to instruments, sectors, and macro factors;
5. assigns materiality, confidence, freshness, and magnitude where available;
6. clusters duplicate/corroborating stories;
7. ranks portfolio relevance by matching event subjects to holdings.

The missing step is **deterministic impact interpretation**.

Today, the code explicitly stops at:

```text
impact.status = "not_calculated"
impact_calculation = "not_implemented_without_verified_sensitivities"
```

Phase 6.5 must replace that placeholder with a reproducible engine that can answer:

```text
What factor actually changed?
Which companies are economically exposed to that factor?
Is the exposure positive, negative, conditional, or unknown?
How strong and how reliable is that exposure?
How strongly does this particular event activate that exposure?
How much of a portfolio is exposed?
How should the result be ranked now?
```

It must **not** answer:

```text
How many percent will the stock rise?
What exact return will the portfolio earn because of this event?
```

unless a separately validated forecasting model is added later.

The output is therefore a **directional exposure / impact score**, not an expected-return forecast.

---

# 1. Current repo integration points

Phase 6.5 must extend the existing implementation rather than create a parallel intelligence subsystem.

Existing files that Phase 6.5 builds on:

```text
apps/api/app/domain/event_intelligence.py
apps/api/app/services/event_intelligence_service.py
apps/api/app/models/workstation.py
apps/api/app/jobs/evidence_tasks.py
apps/api/app/services/context_builder.py
apps/api/app/models/market.py
```

Existing behavior:

### `domain/event_intelligence.py`

Already owns:

- `EVENT_RULES`
- deterministic event classification
- factor assignment
- `detect_magnitude()`
- `event_materiality()`
- `event_confidence()`
- `event_freshness()`
- deterministic clustering identity

Phase 6.5 should keep this file responsible for **pure event-domain rules**.

### `services/event_intelligence_service.py`

Already owns:

- conversion from raw `Event` → `NormalizedEvent`
- subject derivation
- source/corroboration handling
- normalized-event persistence
- duplicate clustering
- event serialization
- company/portfolio event queries

This remains the service boundary for **persisted event intelligence**.

### `models/workstation.py`

Already contains:

- `NormalizedEvent`
- `NormalizedEventEvidence`
- `NormalizedEventSubject`
- `Instrument`
- `PortfolioHolding`
- raw `Event` and `EventSource`

Phase 6.5 extends this model layer with sensitivity and impact records.

### `jobs/evidence_tasks.py`

Today `evidence.index` does:

```text
selected evidence
    ↓
normalize_raw_event(...)
```

Phase 6.5 must enqueue impact calculation **after** normalization rather than calculate impacts inline inside the evidence-index task.

Reason:

```text
evidence ingestion success must not depend on impact-model success
```

This preserves the Phase 1 requirement that provider/processing failures remain decoupled.

### `services/context_builder.py`

The `EVENTS` section currently reads normalized events and includes them in Canonical Intelligence Context.

After Phase 6.5, this section must consume the persisted company impact result so:

```text
Company page
Research
Assistant
Portfolio intelligence
```

all see the same deterministic impact assessment.

---

# 2. Non-goals

Phase 6.5 does **not** implement:

- stock-price prediction;
- an LLM impact classifier;
- autonomous buy/sell recommendations;
- a causal ML model claiming that an event caused a specific return;
- arbitrary sentiment scoring;
- a second event table unrelated to `NormalizedEvent`;
- a giant factor knowledge graph;
- Redis as the authoritative store;
- a separate RAG path for event impacts.

The initial engine is intentionally conservative.

If direction cannot be determined from verified rules/data:

```text
direction = unknown
impact_status = unresolved
```

That is a valid result.

The system must prefer:

```text
"I know this is relevant but cannot verify direction"
```

over:

```text
"probably positive"
```

---

# 3. Separate four concepts that must not be conflated

The engine must persist and expose four different quantities.

## 3.1 Event severity / shock strength

Question:

> How large is the underlying event or factor movement?

Range:

```text
0.0 → 1.0
```

Example:

```text
25 bp policy-rate move  → smaller shock
200 bp policy-rate move → larger shock
```

This is event-specific.

## 3.2 Company factor sensitivity

Question:

> If this factor rises, what is the company's structural directional exposure?

Range:

```text
-1.0 → +1.0
```

Interpretation:

```text
+1.0  strong positive exposure to factor increase
+0.4  moderate positive exposure
 0.0  no verified directional exposure
-0.4  moderate negative exposure
-1.0  strong negative exposure
```

Example:

```text
OGDC × Brent increase → positive sensitivity
airline × oil increase → negative sensitivity
```

This is company/factor-specific and exists independently of any individual news event.

## 3.3 Event-company impact score

Question:

> Given this event and this company's sensitivity, how strongly is this event directionally relevant to this company?

Range:

```text
-1.0 → +1.0
```

This is the main Phase 6.5 company result.

It is **not a predicted return percentage**.

## 3.4 Current priority score

Question:

> How important is this event to surface right now?

Range:

```text
0.0 → 1.0
```

This includes freshness decay.

Critical rule:

```text
freshness MUST NOT modify the stored historical economic impact score.
```

An oil shock that was strongly positive for an E&P company does not become economically weaker merely because 60 days passed.

Instead:

```text
impact_score   = stable event/company interpretation
priority_score = abs(impact_score) × freshness_score
```

The UI/Assistant can rank with `priority_score` while still accurately representing historical impact.

---

# 4. Canonical factor ontology

The current `NormalizedEvent.factor` values are useful event categories but are too broad for actual economic sensitivities.

For example:

```text
oil_commodities
```

cannot distinguish:

```text
Brent crude
natural gas
LNG
coal
cotton
urea
gold
```

Phase 6.5 therefore introduces a **versioned code-level factor registry**.

Do not create a mutable `factor_definitions` database table initially.

Reason:

- factor semantics are application logic;
- every factor must have tests;
- changing semantics must be code-reviewed;
- versioning in Git is preferable to silent DB edits.

Create:

```text
apps/api/app/domain/factor_intelligence.py
```

with a structure such as:

```python
@dataclass(frozen=True)
class FactorDefinition:
    key: str
    category: str
    direction_unit: str
    source_series_keys: tuple[str, ...]
    shock_method: str
    saturation_value: Decimal | None
```

Initial factor registry should remain limited to factors for which the existing product can obtain defensible inputs.

Recommended initial keys:

```text
policy_rate
kibor
usd_pkr
brent_oil
natural_gas
coal
cotton
urea
freight
electricity_tariff
gas_tariff
geopolitical_risk
regulation
company_earnings
company_operations
company_financing
company_governance
```

Not all factors need quantitative macro time series.

Examples:

```python
policy_rate:
    category = "rates"
    source_series_keys = ("PK_POLICY_RATE",)
    shock_method = "bps"

usd_pkr:
    category = "fx"
    source_series_keys = ("PK_USD_PKR",)
    shock_method = "percent"

brent_oil:
    category = "commodity"
    source_series_keys = ("BRENT_USD_BBL",)
    shock_method = "percent"

geopolitical_risk:
    category = "qualitative"
    source_series_keys = ()
    shock_method = "materiality"

company_operations:
    category = "issuer_specific"
    source_series_keys = ()
    shock_method = "event_rule"
```

---

# 5. Map normalized events into canonical factors

Create a pure function in:

```text
apps/api/app/domain/factor_intelligence.py
```

```python
resolve_event_factors(
    event_type: str,
    current_factor: str | None,
    title: str,
    evidence_text: str,
) -> tuple[ResolvedFactor, ...]
```

A `ResolvedFactor` contains:

```text
factor_key
is_primary
resolution_method
confidence
matched_signal
```

Example:

```text
NormalizedEvent:
    event_type = oil_commodities
    current factor = oil_commodities
    title = "Brent rises 8% after supply disruption"

resolve_event_factors() →

[
    {
        factor_key: "brent_oil",
        is_primary: true,
        resolution_method: "deterministic_phrase",
        confidence: 1.0,
        matched_signal: "brent"
    },
    {
        factor_key: "geopolitical_risk",
        is_primary: false,
        resolution_method: "deterministic_phrase",
        confidence: 0.8,
        matched_signal: "supply disruption"
    }
]
```

This must be deterministic phrase/rule matching only in v1.

Do not ask an LLM what factor is present.

---

# 6. Add normalized event factors as a persisted relation

A single `NormalizedEvent.factor` field cannot safely support multiple factor exposures.

Add:

```text
normalized_event_factors
```

Model:

```python
class NormalizedEventFactor(Base):
    __tablename__ = "normalized_event_factors"
```

Columns:

```text
id
normalized_event_id FK → normalized_events.id
factor_key
is_primary
resolution_method
resolution_confidence
shock_direction
shock_strength
raw_magnitude
raw_magnitude_unit
shock_status
methodology_version
details_json
created_at
updated_at
```

Unique constraint:

```text
(normalized_event_id, factor_key, methodology_version)
```

Indexes:

```text
factor_key
normalized_event_id
shock_status
```

The existing `NormalizedEvent.factor` remains temporarily for backward compatibility.

After Phase 6.5 stabilizes:

```text
NormalizedEvent.factor = legacy primary classification
NormalizedEventFactor = authoritative impact factors
```

Do not immediately remove the old column.

---

# 7. Determining shock direction

Shock direction refers to the **factor**, not the company.

Values:

```text
increase
decrease
neutral
unknown
```

Convert internally to:

```text
increase = +1
decrease = -1
neutral  = 0
unknown  = None
```

Examples:

```text
"SBP raises policy rate 100 bps"
factor = policy_rate
shock_direction = increase

"PKR appreciates 3%"
factor = usd_pkr
shock_direction = decrease
```

For `usd_pkr`, the factor is explicitly defined as:

```text
PKR per USD
```

Therefore:

```text
USD/PKR rises  → PKR depreciation → factor increase
USD/PKR falls  → PKR appreciation → factor decrease
```

This semantic definition must live in `FactorDefinition`, not be inferred ad hoc in service code.

---

# 8. Determining quantitative shock strength

`shock_strength` is a bounded severity measure used for ranking.

It is not an expected-return estimate.

Use the existing materiality thresholds as anchors so the new scoring does not contradict Phase 6.

## 8.1 Rates

Existing Phase 6 materiality:

```text
< 25 bps   → low
25–99 bps  → medium
>=100 bps  → high
```

Use a monotonic normalized transform:

```python
strength = min(abs(bps) / 150.0, 1.0)
```

Why 150?

- 25 bp → 0.167
- 50 bp → 0.333
- 100 bp → 0.667
- 150+ bp → saturates at 1.0

The exact saturation constant is **methodology configuration** and therefore versioned.

It must be backtestable and changeable without changing historical source data.

Do not call this a probability or return.

## 8.2 FX

Existing Phase 6 materiality:

```text
< 2%   → low
2–4.99 → medium
>=5%   → high
```

Use:

```python
strength = min(abs(percent_change) / 7.5, 1.0)
```

Examples:

```text
2%  → 0.267
5%  → 0.667
7.5%+ → 1.0
```

## 8.3 Brent / commodity price changes

For an explicitly reported percentage movement:

```python
strength = min(abs(percent_change) / 10.0, 1.0)
```

So:

```text
2% move  → 0.20
5% move  → 0.50
10% move → 1.00
```

Do not use a single 10% constant for all commodities forever.

Each factor definition owns its own saturation threshold.

Example:

```text
brent_oil.saturation_value = 10%
natural_gas.saturation_value = 15%
cotton.saturation_value = 10%
```

Initial values are methodology parameters, not claimed universal truths.

---

# 9. Quantitative magnitude extraction must be factor-aware

The current `detect_magnitude()` returns the first `%` or `bps` match.

That is acceptable for Phase 6 classification but too weak for impact calculation.

Example bad input:

```text
"Inflation fell to 7.2% while SBP cut rates by 100 bps"
```

A generic first-number parser could pair the wrong number with the factor.

Phase 6.5 must add factor-specific extractors.

Create:

```text
apps/api/app/domain/event_shocks.py
```

Functions:

```python
extract_rate_shock(text) -> ShockObservation | None
extract_fx_shock(text) -> ShockObservation | None
extract_commodity_shock(text, factor_key) -> ShockObservation | None
extract_qualitative_shock(...) -> ShockObservation
```

A `ShockObservation` contains:

```text
factor_key
direction
magnitude
unit
strength
matched_text
extraction_method
confidence
```

Rate parser only accepts numbers syntactically close to:

```text
rate
policy rate
SBP
bps
basis points
hike
cut
```

FX parser only accepts numbers syntactically close to:

```text
USD/PKR
rupee
PKR
depreciation
appreciation
exchange rate
```

Commodity parser requires the target commodity name near the numeric phrase.

This prevents cross-factor number contamination.

---

# 10. Verify quantitative shocks against structured data when possible

If an event claims a factor move and the canonical macro database contains the same factor, verify it.

Existing usable data source:

```text
macro_observations
    series_id
    effective_date
    value
    is_selected
    provider provenance
```

Process:

```text
1. resolve factor → canonical macro series key
2. obtain selected observation closest to event effective date
3. obtain previous selected observation
4. calculate actual structured change
5. compare event-text magnitude/direction with structured change
```

Example:

```text
event says:
    policy rate cut 100 bps

macro:
    previous = 12.5
    current = 11.5

computed:
    -100 bps

verification:
    confirmed
```

Store in `NormalizedEventFactor.details_json`:

```json
{
  "text_shock": {
    "direction": "decrease",
    "magnitude": 100,
    "unit": "bps"
  },
  "structured_shock": {
    "previous": 12.5,
    "current": 11.5,
    "computed_change": -100,
    "unit": "bps",
    "series_key": "PK_POLICY_RATE"
  },
  "verification": "confirmed"
}
```

If the text and structured series disagree beyond tolerance:

```text
shock_status = conflict
```

Do not silently choose one.

Directional impact is withheld until conflict resolution.

---

# 11. Qualitative event severity

Many issuer events do not have a meaningful numeric shock.

Examples:

```text
plant shutdown
CEO resignation
licence suspension
contract award
sanctions
```

For these, derive `shock_strength` from the existing event materiality plus event-specific deterministic rules.

Base values:

```text
low     = 0.25
medium  = 0.55
high    = 0.85
unknown = None
```

These numbers are not claims about stock returns.

They only give a stable ranking scale.

Event-specific overrides:

```text
operational_disruption:
    fire/explosion/force majeure/full shutdown → high base
    partial outage/temporary suspension        → medium

regulation:
    licence suspension/ban/material order → high
    ordinary notification/change          → medium

governance:
    CEO/CFO/chair departure → medium
    ordinary board update   → low

corporate_calendar:
    no directional impact
    relevance only

briefing_research:
    no directional impact
    relevance only
```

Every override lives in code with unit tests.

---

# 12. Company sensitivity data model

Add:

```text
company_factor_sensitivities
```

Model:

```python
class CompanyFactorSensitivity(Base):
    __tablename__ = "company_factor_sensitivities"
```

Columns:

```text
id
instrument_id FK
factor_key
sensitivity_score
direction_status
source_type
confidence
evidence_document_id nullable
evidence_artifact_id nullable
valid_from
valid_to nullable
as_of_date
methodology_version
details_json
created_at
updated_at
```

`sensitivity_score`:

```text
Numeric(8,6)
bounded [-1, +1]
```

`direction_status`:

```text
resolved
conditional
conflicted
unknown
```

`source_type`:

```text
company_structural
sector_structural
empirical
manual_verified_override
```

Do not store one anonymous sensitivity with no provenance.

Every sensitivity must explain:

```text
why it exists
which methodology created it
which evidence/rule supports it
when it is valid
```

---

# 13. Sensitivity source hierarchy

The resolver must not average every available score blindly.

Use a defined hierarchy.

## Level A — verified company-specific structural exposure

Highest priority.

Examples:

```text
E&P company produces oil → Brent positive
airline consumes fuel → Brent negative
export-heavy textile company earns USD → USD/PKR increase generally positive
import-heavy assembler buys USD inputs → USD/PKR increase generally negative
```

This score should only exist when a company-specific rule/evidence is available.

Initial company-specific rules can be created for:

```text
portfolio holdings
benchmark constituents
deep-requested companies
promoted screening candidates
```

Do not manually curate all 862 instruments before the system is useful.

## Level B — sector structural exposure

Fallback.

Create:

```text
apps/api/app/domain/sector_factor_exposures.py
```

Registry:

```python
SECTOR_FACTOR_EXPOSURES = {
    "OIL & GAS EXPLORATION COMPANIES": {
        "brent_oil": (+0.90, 0.85),
        "usd_pkr": (+0.55, 0.70),
    },
    ...
}
```

Tuple:

```text
(sensitivity_score, confidence)
```

The exact PSX sector strings should be read from the existing `Instrument.sector` values and normalized through one canonical function.

Do not scatter `if "textile" in sector` throughout the codebase.

---

# 14. Initial sector exposure registry

The first registry should remain conservative.

## Oil & Gas Exploration

```text
brent_oil    +0.90 confidence 0.85
usd_pkr      +0.55 confidence 0.70
```

Reason:

- realized hydrocarbon revenue is structurally tied to energy economics;
- PKR depreciation can increase PKR translation of USD-linked economics;
- actual company contract/pricing details vary, therefore not +1.0 confidence.

## Oil marketing / refining

Do not assign one simple oil sign universally.

Use:

```text
brent_oil → conditional
```

Reason:

```text
inventory gains/losses
regulated pricing
working-capital effects
margin mechanics
timing
```

Until company-specific logic is implemented:

```text
direction_status = conditional
directional score = withheld
relevance score = allowed
```

## Commercial banks

Do not hard-code:

```text
higher rates = positive
```

The net effect depends on:

```text
asset repricing
deposit beta
duration
government-security books
credit quality
NPL cycle
```

Initial result:

```text
policy_rate → conditional
kibor       → conditional
```

The event remains relevant but the engine does not invent direction.

## Textile exporters

Potential registry:

```text
usd_pkr            +0.55 confidence 0.65
cotton             -0.65 confidence 0.70
gas_tariff         -0.60 confidence 0.70
electricity_tariff -0.60 confidence 0.70
freight            -0.35 confidence 0.55
```

This remains a sector fallback, not company truth.

## Cement

Potential registry:

```text
coal               -0.70 confidence 0.75
electricity_tariff -0.45 confidence 0.65
policy_rate        -0.30 confidence 0.50
```

Rates receive lower confidence because demand/capital structure differ by company.

## Fertilizer

Potential registry:

```text
gas_tariff   -0.80 confidence 0.80
urea_price   +0.65 confidence 0.65
usd_pkr      conditional
```

---

# 15. Company-specific structural overrides

Company overrides must be evidence-backed.

Do not create a hard-coded Python dictionary such as:

```python
"OGDC": {"brent_oil": 1.0}
```

with no provenance.

Instead, seed `CompanyFactorSensitivity` records through a service.

Create:

```text
apps/api/app/services/factor_sensitivity_service.py
```

Function:

```python
derive_structural_sensitivities(
    db: Session,
    instrument_id: str,
) -> list[CompanyFactorSensitivity]
```

Resolution order:

```text
1. verified company-specific override/evidence
2. sector exposure registry
3. empirical estimate if statistically valid
4. unresolved
```

For a sector-derived record store:

```json
{
  "sector": "OIL & GAS EXPLORATION COMPANIES",
  "registry_version": "sector-factor-v1",
  "reason": "sector_structural_fallback"
}
```

For a company-specific record:

```json
{
  "reason": "issuer_business_model",
  "evidence_document_id": "...",
  "evidence_page": 42,
  "matched_disclosure": "..."
}
```

Do not store long disclosure text; store a short matched phrase or evidence reference.

---

# 16. Empirical sensitivities

Empirical sensitivity is supporting evidence, not the primary truth engine.

Create:

```text
apps/api/app/services/factor_regression_service.py
```

Initial supported factors:

```text
brent_oil
usd_pkr
natural_gas
```

Do not initially regress sparse policy-rate decision events as if they were daily continuous factors.

---

# 17. Empirical data preparation

Company daily price history:

Use canonical/selected market history already present in the repo.

Do not query Yahoo or another provider inside the regression service.

The regression reads only persisted canonical data.

For each company:

```text
P_t = selected daily close
r_company,t = ln(P_t / P_t-1)
```

Factor return:

```text
F_t = selected structured factor level
r_factor,t = ln(F_t / F_t-1)
```

For USD/PKR:

```text
positive factor return = PKR depreciation
```

because factor level is PKR per USD.

---

# 18. Market control for regressions

Do not interpret raw company/factor correlation as factor sensitivity because both may simply respond to the general market.

Use:

```text
r_company,t =
    alpha
    + beta_market * r_market,t
    + beta_factor * r_factor,t
    + error_t
```

If a reliable KSE benchmark total-return history is not yet available, derive a temporary PSX equal-weight control from the canonical equity universe:

```text
for each trading day:
    collect valid returns for active ordinary equities
    require minimum breadth
    market_return = equal-weight mean return
```

Recommended first implementation:

```text
equal-weight mean
minimum 100 valid instruments/day
winsorize individual daily returns at 1st/99th percentile before averaging
```

Store the derived daily market-control series or cache its deterministic calculation.

Do not use `SectorDailyStats.average_change_percent` as a replacement for a broad-market return without verifying its construction.

---

# 19. Regression window

Use:

```text
lookback target = 3 years
minimum aligned observations = 180
preferred aligned observations >= 250
```

Also compute two subwindows:

```text
recent half
older half
```

The sign must be reasonably stable.

---

# 20. Regression quality gates

An empirical sensitivity is accepted only if all required checks pass.

Required:

```text
aligned observations >= 180
factor variance > minimum epsilon
beta is finite
standard error is finite
|t-stat(beta_factor)| >= 1.96
recent/older subwindow signs do not strongly contradict
no single observation dominates fit
```

Recommended additional diagnostics:

```text
R²
adjusted R²
beta confidence interval
residual diagnostics
```

Do not treat statistical significance as economic truth.

The empirical record gets a maximum confidence cap.

Example:

```text
empirical confidence <= 0.70
```

---

# 21. Normalize empirical beta into the sensitivity scale

Regression beta is not naturally bounded to `[-1, 1]`.

Do not simply clamp raw beta.

First standardize factor returns:

```text
z_factor,t =
    r_factor,t / sample_std_factor
```

Regression coefficient then represents approximate company return sensitivity to one factor-standard-deviation move.

Map it through a bounded monotonic transform:

```python
score = tanh(beta_factor_standardized)
```

Store both:

```text
raw_beta
normalized_score
```

Never discard the raw statistical estimate.

---

# 22. Resolving multiple sensitivity sources

Create:

```python
resolve_company_factor_sensitivity(...)
```

Output:

```text
resolved_score
resolved_confidence
status
supporting_sources
conflicts
methodology_version
```

Rules:

### Case 1 — company structural available

Use it as anchor.

If empirical sign agrees:

```text
score =
    0.75 * structural_score
    + 0.25 * empirical_score
```

Confidence:

```text
min(0.95, structural_confidence + empirical_confirmation_bonus)
```

Bonus maximum:

```text
+0.10
```

### Case 2 — company structural absent, sector structural available

Sector structural becomes anchor.

If empirical sign agrees:

```text
score =
    0.65 * sector_score
    + 0.35 * empirical_score
```

### Case 3 — structural and empirical strongly disagree

Example:

```text
structural = +0.80 confidence .85
empirical  = -0.65 confidence .70
```

Do not average them into near zero and pretend certainty.

Output:

```text
status = conflicted
directional_score = null
relevance_score still allowed
```

Persist both sources in `details_json`.

### Case 4 — only empirical available

Allowed only if all regression quality gates pass.

Output:

```text
source_type = empirical
confidence capped <= .65
```

### Case 5 — no defensible sensitivity

Output:

```text
status = unresolved
directional_score = null
```

The event can still be surfaced through entity relevance/materiality.

---

# 23. Direct issuer-specific events

Not every company event should pass through macro-factor sensitivity.

Examples:

```text
plant shutdown
licence suspension
company-specific financing
earnings release
CEO resignation
```

Introduce direct deterministic rules.

Create:

```text
DIRECT_EVENT_EFFECT_RULES
```

inside:

```text
apps/api/app/domain/event_impacts.py
```

## Operational disruption

If the event directly targets the issuer and matches:

```text
shutdown
fire
explosion
force majeure
production suspension
```

direction:

```text
negative
```

Store method:

```text
direct_event_rule
```

rather than fabricating a permanent company factor sensitivity.

## Licence suspension / ban

Direct issuer regulation:

```text
direction = negative
```

when the event text deterministically identifies suspension/ban.

Ordinary regulatory notification:

```text
direction = unknown
```

unless the economic direction is explicit.

## Earnings

An event titled:

```text
"Quarterly Results"
```

does **not** imply positive or negative direction.

Direction requires structured comparison.

Future deterministic earnings direction may use:

```text
PAT YoY
EPS YoY
revenue growth
margin movement
```

from `FinancialFact`.

Until that comparison is implemented:

```text
impact_status = relevance_only
direction = unknown
```

Do not sentiment-classify earnings text with the LLM.

## Financing

Debt issuance is not universally positive or negative.

Initial:

```text
direction = conditional
```

unless a deterministic rule has enough context.

## Governance

CEO/CFO changes are materiality/relevance signals.

Initial directional result:

```text
unknown
```

unless the event is an explicitly negative occurrence such as removal due to enforcement, which needs its own rule.

---

# 24. Event-company impact data model

Add:

```text
event_company_impacts
```

Model:

```python
class EventCompanyImpact(Base):
    __tablename__ = "event_company_impacts"
```

Columns:

```text
id
normalized_event_id FK
instrument_id FK
factor_key nullable
impact_status
direction
impact_score nullable
relevance_score
impact_confidence
priority_score
shock_strength
sensitivity_score nullable
event_confidence
sensitivity_confidence nullable
link_confidence
directness_multiplier
methodology_version
components_json
evaluated_at
updated_at
```

Unique:

```text
(normalized_event_id, instrument_id, factor_key, methodology_version)
```

Indexes:

```text
instrument_id, priority_score
normalized_event_id
impact_status
```

---

# 25. Event-company impact formula

For factor-based events:

```text
D  = shock direction sign (-1 or +1)
S  = shock strength [0,1]
E  = resolved company sensitivity [-1,+1]
Ce = event confidence [0,1]
Cs = sensitivity confidence [0,1]
Cl = entity-link/factor-resolution confidence [0,1]
M  = directness multiplier [0,1]
F  = existing event freshness score [0,1]
```

Economic impact score:

```text
impact_score =
    D × S × E × Ce × Cs × Cl × M
```

Important:

```text
FRESHNESS IS NOT INCLUDED HERE.
```

Current priority score:

```text
priority_score =
    abs(impact_score) × F
```

Impact confidence:

```text
impact_confidence =
    Ce × Cs × Cl
```

Relevance score, usable even when direction is unresolved:

```text
relevance_score =
    S × Ce × Cl × M
```

If no valid `E`:

```text
impact_score = null
relevance_score remains available
```

---

# 26. Directness multiplier

Recommended values:

```text
direct issuer subject     = 1.00
company-specific factor   = 0.95
sector-derived exposure   = 0.85
macro-factor propagation  = 0.75
```

These values are versioned methodology parameters.

They must be stored in `components_json`.

Do not bury them as magic constants inside a service function.

Create:

```text
IMPACT_METHOD_V1
```

configuration object in `domain/event_impacts.py`.

---

# 27. Example calculation

Event:

```text
Brent rises 8%
```

Resolved:

```text
factor = brent_oil
direction D = +1
shock strength S = 0.80
event confidence Ce = 0.94
freshness F = 0.98
```

OGDC resolved sensitivity:

```text
E = +0.90
Cs = 0.85
Cl = 1.00
M = 0.85
```

Impact:

```text
impact_score =
1 × .80 × .90 × .94 × .85 × 1 × .85
≈ +0.489
```

Priority:

```text
.489 × .98 ≈ .479
```

Store:

```json
{
  "direction": "positive",
  "impact_score": 0.489,
  "priority_score": 0.479,
  "impact_confidence": 0.799,
  "methodology_version": "event-impact-v1"
}
```

Interpretation:

```text
moderate/high positive directional exposure
```

NOT:

```text
OGDC is expected to rise 48.9%
```

---

# 28. Impact strength buckets

Recommended:

```text
abs(score) < 0.15       negligible
0.15 <= score < 0.35    low
0.35 <= score < 0.60    medium
>= 0.60                 high
```

Because these thresholds are heuristic:

- keep numeric score available;
- persist methodology version;
- test boundaries;
- do not market them as probabilities.

---

# 29. Multiple factors in one event

A single event may resolve to:

```text
brent_oil
geopolitical_risk
freight
```

Do not sum raw factor impacts blindly because correlated factors could double-count the same event.

For each company:

```text
calculate one impact row per factor
```

Then build an event-level company summary.

Initial aggregation:

```text
primary factor impact = anchor
secondary factors may increase relevance/confidence
```

Directional event score:

```text
use highest-confidence directional factor
```

If two high-confidence factor impacts have opposite signs:

```text
impact_status = mixed
direction = mixed
```

Do not mathematically net them into an apparently precise zero.

Persist factor-level rows so future methodology can improve aggregation without re-ingesting evidence.

---

# 30. Portfolio aggregation

The existing `portfolio_event_exposure()` currently identifies holdings and affected capital weight but does not calculate impact.

Phase 6.5 replaces this placeholder.

For each holding:

```text
w_i = current holding market value / total portfolio value
I_i = EventCompanyImpact.impact_score
```

Holding directional contribution:

```text
C_i = w_i × I_i
```

Portfolio net directional score:

```text
net_score = Σ C_i
```

Portfolio gross directional exposure:

```text
gross_score = Σ w_i × abs(I_i)
```

Affected portfolio weight:

```text
sum of w_i for holdings where:
    relevance_score >= configured threshold
```

Recommended initial relevance threshold:

```text
0.20
```

Current portfolio priority:

```text
portfolio_priority =
    Σ w_i × priority_score_i
```

Again:

```text
NO conversion to predicted P&L.
```

---

# 31. Portfolio interpretation example

Portfolio:

```text
OGDC weight 12%
PPL  weight 8%
LUCK weight 6%
```

Event company scores:

```text
OGDC +0.49
PPL  +0.44
LUCK -0.10
```

Contributions:

```text
OGDC = .12 × .49 = +.0588
PPL  = .08 × .44 = +.0352
LUCK = .06 × -.10 = -.0060
```

Net directional score:

```text
+0.088
```

Gross exposure:

```text
.0588 + .0352 + .0060 = .100
```

The product may state:

```text
"This event has net positive directional exposure to the portfolio,
primarily through OGDC and PPL. 26% of capital is linked to affected
holdings under the current relevance threshold."
```

It may not state:

```text
"The portfolio will gain 8.8%."
```

---

# 32. Portfolio impact cache

Add:

```text
portfolio_event_impacts
```

Model:

```python
class PortfolioEventImpact(Base):
    __tablename__ = "portfolio_event_impacts"
```

Columns:

```text
id
portfolio_id FK
normalized_event_id FK
portfolio_state_hash
affected_weight
net_directional_score nullable
gross_directional_score
priority_score
impact_status
methodology_version
details_json
evaluated_at
```

Unique:

```text
portfolio_id
normalized_event_id
portfolio_state_hash
methodology_version
```

---

# 33. Portfolio state hash

The cache is valid only for a particular portfolio valuation state.

Build the hash from sorted deterministic inputs:

```text
portfolio_id
holding instrument IDs
quantities
canonical holding market values
canonical price trade dates
cash balance
total portfolio value
```

Hash with SHA-256.

If:

```text
holdings change
prices change
cash changes
```

the hash changes and the old cache is not reused.

Old records may remain for audit/reproducibility.

---

# 34. Background computation architecture

Do not calculate impact synchronously inside `evidence.index`.

Current:

```text
evidence.index
    ↓
normalize_raw_event()
```

New:

```text
evidence.index
    ↓
normalize_raw_event()
    ↓
publish event-impact task
    ↓
return evidence.index success
```

Create:

```text
apps/api/app/jobs/event_intelligence_tasks.py
```

Task:

```python
@celery_app.task(name="intelligence.compute_event_impacts")
def compute_event_impacts(normalized_event_id: str):
    ...
```

Queue:

```text
event_intelligence
```

Recommended concurrency:

```text
2
```

Reason:

- CPU/DB work is small;
- event impact failure cannot block evidence indexing;
- no reason for 20-worker concurrency;
- keeps Phase 1 source isolation.

Do not create a scheduler for this if event-driven task publication is sufficient.

---

# 35. Event impact task steps

For one `normalized_event_id`:

```text
1. load NormalizedEvent
2. load retained evidence/subjects
3. build event text from retained bounded evidence
4. resolve canonical factors
5. derive/verify each factor shock
6. upsert NormalizedEventFactor
7. determine candidate instruments:
      direct NormalizedEventSubject instruments
      sector members for sector-relevant factor propagation
      portfolio/deep universe only where appropriate
8. resolve company sensitivity per instrument/factor
9. calculate EventCompanyImpact
10. persist all results in one transaction
11. return counts/status
```

Do not calculate every one of ~862 companies for every global event.

---

# 36. Candidate-company scope

Prevent O(events × full universe) explosion.

For issuer-specific event:

```text
direct linked instruments only
```

For sector event:

```text
active companies in linked sector
```

For broad macro factor:

Use:

```text
portfolio holdings
benchmark universe if available
deep_requested companies
promoted screening candidates
```

This aligns with the broad/deep architecture already used elsewhere.

A broad global oil event does not require writing 862 mostly meaningless impact rows.

---

# 37. Idempotency

Every impact calculation must be reproducible.

Unique key includes:

```text
normalized_event_id
instrument_id
factor_key
methodology_version
```

Task behavior:

```text
existing same-version row with unchanged dependencies → return idempotent
changed event/sensitivity dependency → update
new methodology version → create/rebuild versioned result
```

Store dependency hashes in `components_json`:

```text
event_hash
sensitivity_hash
factor_method_hash
```

This allows exact stale detection.

---

# 38. Recompute triggers

Company impact must be recomputed when:

```text
NormalizedEvent changes
new corroborating evidence changes confidence
NormalizedEventFactor changes
company sensitivity changes
methodology version changes
```

Portfolio impact must be recomputed when:

```text
company impact changes
portfolio holdings change
portfolio valuation/weights change
methodology version changes
```

Do not manually delete cache rows.

Use dependency/state hash mismatch.

---

# 39. Backfill existing normalized events

Create:

```text
apps/api/app/jobs/backfill_event_impacts.py
```

CLI behavior:

```bash
python -m app.jobs.backfill_event_impacts --limit 500
```

Options:

```text
--event-id
--since
--factor
--instrument
--rebuild-version
```

Backfill should:

```text
order newest events first
process medium/high materiality first
skip already-current dependency hashes
commit in bounded batches
print counts
```

Suggested output:

```json
{
  "scanned": 500,
  "factor_rows": 620,
  "company_impacts": 410,
  "resolved_direction": 290,
  "relevance_only": 95,
  "conflicted": 12,
  "unresolved": 13
}
```

---

# 40. Replace the current serialization placeholder

Current event serialization returns approximately:

```json
{
  "impact": {
    "status": "not_calculated",
    "direction": null,
    "expected_return": null
  }
}
```

Change it to:

```json
{
  "impact": {
    "status": "resolved",
    "direction": "positive",
    "score": 0.489,
    "strength": "medium",
    "confidence": 0.799,
    "priority_score": 0.479,
    "factor": "brent_oil",
    "methodology_version": "event-impact-v1",
    "expected_return": null
  }
}
```

Keep:

```text
expected_return = null
```

explicitly for now.

---

# 41. Company event query behavior

When:

```python
list_normalized_events(
    subject_type="instrument",
    subject_key="OGDC"
)
```

the service should attach the `EventCompanyImpact` for OGDC.

If event exists but no impact is resolved:

```json
{
  "impact": {
    "status": "unresolved",
    "direction": null,
    "score": null,
    "relevance_score": 0.62,
    "reason": "company_factor_sensitivity_missing"
  }
}
```

Do not drop the event merely because direction is unknown.

---

# 42. Update `portfolio_event_exposure()`

Replace:

```text
impact_direction = None
impact_calculation = not_implemented_without_verified_sensitivities
```

with:

```text
holdings:
    symbol
    current_portfolio_weight
    impact_score
    directional_contribution
    impact_confidence

affected_portfolio_weight
net_directional_score
gross_directional_score
portfolio_priority
impact_status
```

Mixed unresolved/resolved holdings are allowed.

---

# 43. Canonical Intelligence Context integration

`ContextBuilder._events()` currently:

```text
loads material normalized company events
returns admitted event structures
```

After Phase 6.5:

```text
each admitted event must include company impact data
```

The dependency hash for the EVENTS section must additionally include:

```text
EventCompanyImpact.updated_at
methodology_version
impact_status
impact_score
priority_score
```

Otherwise the Context cache could reuse an event section after its impact was recomputed.

---

# 44. Context evidence

Add one calculation EvidenceReference for each resolved company impact.

Classification:

```text
calculation
```

Underlying ID:

```text
event_company_impact:<id>:<methodology_version>
```

Metadata:

```json
{
  "normalized_event_id": "...",
  "factor": "brent_oil",
  "direction": "positive",
  "score": 0.489,
  "methodology_version": "event-impact-v1"
}
```

The Assistant therefore cites a deterministic calculated record rather than inventing impact during synthesis.

---

# 45. Context deficiencies

An event being present and an impact being unresolved are different states.

Do not mark the entire EVENTS section missing if events exist.

Instead:

```text
EVENTS section = CURRENT
event impact_status = unresolved
```

Add a deficiency only where impact is required by the consumer:

```text
category = event_impact
state = NOT_EVALUATED
reason = company factor sensitivity unresolved
```

This is especially useful for `SECURITY_FIT`.

---

# 46. Assistant contract

The LLM receives:

```text
event
factor
impact direction
impact score
impact confidence
priority score
sensitivity provenance
unresolved/conflict flags
```

The LLM may:

```text
explain
compare
synthesize
identify contradictions
describe portfolio relevance
```

The LLM may not:

```text
change impact_score
invent missing direction
convert impact_score into return
infer a numeric expected P&L
```

Prompt rule:

```text
Event impact scores are deterministic directional relevance scores,
not return forecasts. Never express them as predicted percentage returns.
```

---

# 47. Methodology versioning

Define constants:

```text
FACTOR_RESOLUTION_VERSION = "factor-resolution-v1"
SHOCK_METHOD_VERSION = "event-shock-v1"
SECTOR_SENSITIVITY_VERSION = "sector-factor-v1"
EMPIRICAL_SENSITIVITY_VERSION = "factor-regression-v1"
IMPACT_METHOD_VERSION = "event-impact-v1"
```

Every persisted derivative stores the relevant version.

If scoring constants change:

```text
bump methodology version
rebuild derivative rows
do not mutate raw event/evidence
```

---

# 48. Observability

Add event-impact health to existing ingestion/data-health surfaces rather than creating an isolated dashboard.

Track:

```text
normalized events total
medium/high events
events with factor resolution
events with verified shock
company impacts resolved
company impacts relevance_only
company impacts conditional
company impacts conflicted
company impacts unresolved
oldest pending impact
latest successful calculation
last task failure
```

Per-company completeness adds:

```text
event_impact_coverage
```

---

# 49. Error behavior

Impact calculation failure must not mutate normalized evidence into failure.

Rules:

```text
raw evidence remains selected
NormalizedEvent remains valid
impact task records its own error
event can still appear with impact_status = pending/failed
```

If a sensitivity calculation fails:

```text
impact_status = unresolved
reason = sensitivity_error
```

Do not remove the event from Research/Company pages.

---

# 50. Tests — pure domain layer

Create:

```text
app/tests/test_event_shocks.py
app/tests/test_factor_sensitivities.py
app/tests/test_event_impacts.py
```

Required shock cases:

```text
rate hike 100 bps → increase
rate cut 50 bps → decrease
USD/PKR rises 3% → increase
rupee appreciates 3% → usd_pkr decrease
Brent rises 8% → brent increase
unrelated inflation 7% + rate cut 100bp → parser uses 100bp for rate
```

Required no-direction cases:

```text
quarterly results released
board meeting announced
CEO appointed
ordinary regulatory notice
```

---

# 51. Tests — sensitivity resolution

Required:

```text
company override beats sector fallback
sector fallback used when no company rule
agreeing empirical estimate boosts confidence
opposite high-confidence empirical sign → conflicted
invalid empirical regression → ignored
no exposure → unresolved
conditional bank/rate exposure → no directional score
```

---

# 52. Tests — impact formula

Boundary tests:

```text
all components 1 → score ±1
unknown sensitivity → impact_score null
zero shock → score 0
negative sensitivity + positive shock → negative impact
negative sensitivity + negative shock → positive impact
freshness does not alter impact_score
freshness does alter priority_score
```

The final two are mandatory.

---

# 53. Tests — portfolio aggregation

Required:

```text
weights sum correctly
cash does not receive company impact
net score uses signed contributions
gross score uses absolute contributions
affected_weight uses relevance threshold
unresolved holding does not zero resolved holdings
new portfolio state hash invalidates cache
```

---

# 54. Integration tests

End-to-end fixture:

```text
evidence candidate
    ↓
Event
    ↓
NormalizedEvent
    ↓
NormalizedEventFactor
    ↓
CompanyFactorSensitivity
    ↓
EventCompanyImpact
    ↓
ContextBuilder EVENTS
```

Assert the same impact ID/score appears in:

```text
event service
canonical context
assistant evidence input
```

---

# 55. Regression validation before enabling empirical signals

Do not immediately calculate empirical sensitivities for every factor/company and trust them.

Build:

```bash
python -m app.jobs.validate_factor_regressions
```

Report:

```text
factor
companies attempted
accepted regressions
median observations
median beta
sign distribution
failure reasons
unstable-sign count
```

Manually inspect obvious economic cases first.

If results are nonsensical, fix preprocessing/model specification before enabling empirical signals.

---

# 56. Rollout sequence

## Phase 6.5A — schema + factor/shock layer

Implement:

```text
FactorDefinition registry
NormalizedEventFactor
factor-specific shock parsers
structured macro verification
migration
tests
```

Exit criteria:

```text
existing normalized events can be backfilled with factor/shock rows
no company impact yet
```

## Phase 6.5B — structural sensitivities

Implement:

```text
CompanyFactorSensitivity
sector-factor registry
company-specific override service
sensitivity resolver
conditional/conflict states
tests
```

Initial scope:

```text
portfolio holdings
deep companies
major PSX sectors
```

Exit criteria:

```text
a company/factor query returns a fully explained sensitivity or explicit unresolved status
```

## Phase 6.5C — deterministic company impact

Implement:

```text
EventCompanyImpact
direct issuer-event rules
factor impact formula
strength buckets
priority score
Celery impact task
backfill job
event serialization
tests
```

Exit criteria:

```text
event service no longer returns "not_calculated" for supported impacts
```

## Phase 6.5D — portfolio aggregation + canonical context

Implement:

```text
PortfolioEventImpact
portfolio state hash
updated portfolio_event_exposure()
ContextBuilder event impact evidence
dependency hashes
deficiencies
tests
```

Exit criteria:

```text
portfolio + company + ContextBuilder all expose identical deterministic impact records
```

## Phase 6.5E — empirical sensitivity support

Only after A–D are stable.

Implement:

```text
factor_regression_service.py
PSX market control
regression diagnostics
quality gates
empirical sensitivity rows
resolver confirmation/conflict logic
```

Exit criteria:

```text
empirical estimates only influence impacts when all quality gates pass
```

---

# 57. Database migration contents

One migration after current Alembic head.

Create:

```text
normalized_event_factors
company_factor_sensitivities
event_company_impacts
portfolio_event_impacts
```

Do not alter raw:

```text
events
event_sources
documents
source_artifacts
```

Only additive changes.

Keep existing:

```text
NormalizedEvent.factor
```

during migration period.

---

# 58. File-level implementation map

## New files

```text
apps/api/app/domain/factor_intelligence.py
apps/api/app/domain/event_shocks.py
apps/api/app/domain/event_impacts.py
apps/api/app/domain/sector_factor_exposures.py
apps/api/app/services/factor_sensitivity_service.py
apps/api/app/services/factor_regression_service.py
apps/api/app/jobs/event_intelligence_tasks.py
apps/api/app/jobs/backfill_event_impacts.py
```

## Modified files

```text
apps/api/app/models/workstation.py
apps/api/app/services/event_intelligence_service.py
apps/api/app/jobs/evidence_tasks.py
apps/api/app/services/context_builder.py
apps/api/app/celery_app.py
docker-compose.yml
apps/api/app/services/data_health_service.py
```

---

# 59. What NOT to put in LangGraph later

Phase 6.5 is deterministic backend intelligence.

LangGraph should later consume its result.

Do not create a graph node that asks:

```text
"LLM: is oil good or bad for OGDC?"
```

Correct flow:

```text
Phase 6.5 deterministic engine
    ↓
Canonical Intelligence Context
    ↓
LangGraph Phase 8
    ↓
LLM synthesis
```

LangGraph may orchestrate:

```text
retrieve event impacts
retrieve portfolio exposure
retrieve evidence
check deficiencies
synthesize explanation
```

It must not become the source of factor/sensitivity calculations.

---

# 60. Final Phase 6.5 output contract

For a supported company/event pair:

```json
{
  "event_id": "normalized-event-id",
  "symbol": "OGDC",
  "factor": "brent_oil",
  "shock": {
    "direction": "increase",
    "strength": 0.8,
    "magnitude": 8.0,
    "unit": "percent",
    "verification": "confirmed"
  },
  "sensitivity": {
    "score": 0.9,
    "direction": "positive",
    "confidence": 0.85,
    "source": "sector_structural",
    "status": "resolved"
  },
  "impact": {
    "status": "resolved",
    "direction": "positive",
    "score": 0.489,
    "strength": "medium",
    "confidence": 0.799,
    "priority_score": 0.479,
    "expected_return": null
  },
  "methodology": {
    "factor_resolution": "factor-resolution-v1",
    "shock": "event-shock-v1",
    "sensitivity": "sector-factor-v1",
    "impact": "event-impact-v1"
  }
}
```

That record is used by:

```text
Company page
Market page
Portfolio event exposure
Research
Canonical Intelligence Context
Assistant / LangGraph
future monitoring and alerts
```

---

# 61. Definition of done

- [ ] Material normalized events resolve to canonical factor rows or explicit unresolved status.
- [ ] Quantitative shocks are factor-aware rather than using the first arbitrary number in text.
- [ ] Structured macro observations verify quantitative shocks where data exists.
- [ ] Company factor sensitivities have explicit provenance and confidence.
- [ ] Sector assumptions are centralized and versioned.
- [ ] Conditional sectors/factors do not receive fake directional scores.
- [ ] Empirical sensitivities pass minimum-sample, significance, and stability gates.
- [ ] Structural/empirical conflicts are surfaced rather than silently averaged.
- [ ] Direct issuer events use explicit deterministic rules.
- [ ] Event-company impact is stored independently from freshness.
- [ ] Priority score decays with freshness.
- [ ] Impact score is never represented as expected return.
- [ ] Portfolio exposure uses current canonical portfolio weights.
- [ ] Portfolio cache invalidates through deterministic state hashes.
- [ ] Evidence ingestion succeeds even when impact calculation fails.
- [ ] Existing normalized events can be backfilled idempotently.
- [ ] ContextBuilder consumes persisted impact records.
- [ ] Assistant receives impact through canonical evidence instead of calculating it.
- [ ] Data health exposes impact coverage and failures.
- [ ] Unit and integration tests cover direction, conflict, freshness, portfolio aggregation, and unresolved states.

---

# 62. End-state after Phase 6.5

```text
Evidence
    ↓
Normalized Event
    ↓
Canonical Factor Shock
    ↓
Verified Company Sensitivity
    ↓
Deterministic Event-Company Impact
    ↓
Portfolio Aggregation
    ↓
Canonical Intelligence Context
    ↓
Phase 8 LangGraph reasoning
    ↓
Grounded explanation / decision support
```

Boundary:

```text
Phase 6.5 decides WHAT the verified exposure is.
Phase 8 explains WHAT that exposure means in context.
```

The deterministic layer remains auditable, reproducible, versioned, and usable even when no LLM is configured.
