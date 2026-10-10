"""Cached AI market and portfolio briefs.

Facts come only from database queries. Page reads never call the model: a brief is served from cache
until its input hash changes (new trading day, market close, a new classified event, changed holdings),
and then one background generation is started for that hash. Failed hashes are not retried automatically.
"""
import asyncio, json, logging, re
from datetime import UTC, datetime, timedelta
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.db.session import SessionLocal
from app.domain.research_relevance import canonical, fingerprint, utc
from app.models.research_intelligence import AIBrief
from app.services.research_job_service import generation_config

log = logging.getLogger(__name__)
VERSION = 'brief.v3'
RUNNING_TTL = timedelta(minutes=5)
_inflight: set[tuple[str, str, str, str]] = set()

STYLE = (
    "STYLE REFERENCE (a US-market brief; reuse its voice and structure only, never its facts):\n"
    "headline: \"Yields keep pressuring stocks as earnings take the wheel\"\n"
    "section 1 title: \"Rates Keep Pressing Stocks\" / body: \"Yields stayed in control today, and that kept pressure on the broader "
    "market while the big index trackers struggled to find a clean bid. The latest policy readthrough still points to more tightening risk, "
    "which keeps long-duration stocks sensitive. That means traders are still treating rates as the main force behind every rally and fade.\" "
    "/ question: \"How long can stocks hold up with yields still rising?\"\n"
    "section 2 title: \"Tech Loses Its Cushion\" / body: \"Tech gave back support as higher rates hit the group's valuations. For traders, "
    "the message is clear: the market is rewarding earnings, but it is punishing expensive growth names first.\" "
    "/ question: \"Why is tech still getting hit harder than the rest of the market?\"\n"
    "section 3 title: \"Earnings Take Center Stage\" / body: \"Earnings are now the main story. Guidance, not the index tape, is driving "
    "single-stock swings, which makes management commentary the key signal into the next session.\" / question: \"Which earnings reactions can shape tomorrow's open?\"\n"
    "Notice what the bodies do: they interpret (what is driving the tape, what it means for a trader, what is being rewarded or punished) "
    "and almost never quote figures. The numbers live in the ticker chips, which the app fills in from the database."
)
RULES = (
    "Return JSON: {\"headline\": str (<=110 chars, one sentence naming the dominant theme as a takeaway, not a data readout), "
    "\"summary\": str (2 plain sentences, <=45 words, a modest read of the whole picture, at most one figure), "
    "\"sections\": [{\"title\": str (2-5 words, a takeaway like 'Rates Keep Pressing Stocks'), \"body\": str (2-3 sentences of ANALYSIS: "
    "what is driving this, what it implies for a trader or investor, what is being rewarded or punished), "
    "\"question\": str (a natural follow-up a reader would ask, ending in ?), \"tickers\": [str] (1-4 symbols from the cited facts "
    "that illustrate the section; the app shows their % moves), \"fact_ids\": [str]}] (exactly 3), "
    "\"events\": [str] (0-3 items; only upcoming or scheduled things a FACT explicitly states, else [])}. "
    "HARD RULES: use FACTS only; no outside knowledge; never invent numbers, causes, forecasts or dates; no trade instructions. "
    "You may INFER relationships between facts (for example breadth versus the index move, small-cap versus large-cap leadership, "
    "concentration, divergence from the benchmark) but word inferences as readings of the data, not certainties. "
    "NUMBERS: a section body may contain at most ONE figure, and the headline and titles none. Do not restate index levels, "
    "point changes, prices, volumes, counts or percentages the reader can see elsewhere; refer to them in words "
    "('a narrow advance', 'most of the move came from one holding'). "
    "Each section covers a DIFFERENT theme and none repeats another section or the summary. Every section cites its fact ids."
)
SYSTEM = (
    "You are a sharp markets editor writing a short brief for a Pakistan Stock Exchange investor. " + RULES + "\n\n"
    "THEMES for the three sections: (1) what the index and market breadth say about conviction behind the move, "
    "(2) who led and who lagged and what that says about risk appetite (leaders, laggards, sectors), (3) what events or missing data matter next.\n\n" + STYLE
)
PORTFOLIO_SYSTEM = (
    "You are a sharp portfolio analyst writing a short brief for the owner of this Pakistan Stock Exchange portfolio, addressed as 'your portfolio'. "
    + RULES.replace("a modest read of the whole picture", "a modest read of how the portfolio is doing") + "\n\n"
    "THEMES for the three sections: (1) performance versus the benchmark and what actually drove it (contribution, not just direction), "
    "(2) concentration and exposure: single names, sectors and cash, and the risk that creates, "
    "(3) events or data gaps affecting the holdings. Tickers must be holdings.\n\n" + STYLE
)
COMPANY_SYSTEM = (
    "You are a sharp equity analyst writing a short brief on one Pakistan Stock Exchange company for an investor. "
    + RULES.replace("a modest read of the whole picture", "a modest read of the company right now") + "\n\n"
    "THEMES for the three sections: (1) what the latest price action and valuation context say about how the market is treating the stock, "
    "(2) what the filed financials say about earnings quality, leverage or growth (words, not a data dump), "
    "(3) which recent events or missing data matter next. Tickers, if any, must be the company's own symbol.\n\n" + STYLE
)
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


def _too_numeric(brief):
    """True when the model restated figures instead of analysing: bodies carry at most one figure, headline and titles none."""
    texts = [brief["headline"]] + [sec["title"] for sec in brief["sections"]]
    return any(_NUM.search(t) for t in texts) or any(len(_NUM.findall(sec["body"])) > 1 for sec in brief["sections"])


def _pct(v):
    return None if v is None else round(float(v), 2)


def market_facts(db):
    from app.services.market_service import get_market_overview
    from app.services.pipeline.event_reads import event_records
    ov = get_market_overview(db)
    facts, sources = [], {}
    def add(text, source):
        fid = f"f{len(facts) + 1}"; facts.append({"id": fid, "text": text, "source": source}); return fid
    snap = ov.snapshot
    if snap:
        add(f"{snap.index_name} {float(snap.index_value):,.2f}, change {float(snap.index_change):+,.2f} ({_pct(snap.index_change_percent)}%), "
            f"volume {snap.total_volume:,}; {'intraday observation' if ov.price_basis == 'intraday' else 'daily close'} dated {snap.snapshot_date}.",
            f"market snapshot {snap.snapshot_date} ({snap.source})")
    for label, rows in (("gainer", ov.top_gainers[:4]), ("loser", ov.top_losers[:4]), ("volume leader", ov.top_volume[:4])):
        for r in rows:
            add(f"Top {label}: {r.symbol} closed {float(r.close):,.2f} ({_pct(r.change_percent)}%), volume {r.volume:,}, {r.trade_date}.", f"market prices {r.trade_date}")
    for s in sorted(ov.sectors, key=lambda s: -abs(float(s.average_change_percent)))[:5]:
        add(f"Sector {s.sector}: average change {_pct(s.average_change_percent)}%, {s.advancers} up / {s.decliners} down, {s.trade_date}.", f"sector stats {s.trade_date}")
    up, down = sum(s.advancers for s in ov.sectors), sum(s.decliners for s in ov.sectors)
    flat = sum(s.unchanged for s in ov.sectors)
    if up + down + flat:
        add(f"Breadth: {up} advancers, {down} decliners, {flat} unchanged across {up + down + flat} stocks; "
            f"{'more stocks rose than fell' if up > down else 'more stocks fell than rose' if down > up else 'rises and falls were even'}.", f"sector stats {ov.trade_date}")
    if snap and ov.top_gainers:
        avg = sum(float(r.change_percent) for r in ov.top_gainers[:4]) / len(ov.top_gainers[:4])
        add(f"The four top gainers averaged {avg:+.2f}% against an index move of {_pct(snap.index_change_percent)}%, "
            f"so the leaders moved roughly {abs(avg / float(snap.index_change_percent)):.0f}x the index." if snap.index_change_percent else
            f"The four top gainers averaged {avg:+.2f}% while the index was unchanged.", f"market prices {ov.trade_date}")
    events = event_records(db, window_days=7, limit=6)
    for e in events:
        add(f"Event ({str(e['occurred_at'])[:10]}, {e['materiality']}): {e['title']}", "classified event " + e['event_key'])
    key_inputs = {"trade_date": str(ov.trade_date), "basis": ov.price_basis, "events": [e['event_key'] for e in events]}
    return facts, key_inputs


def portfolio_facts(db, user, portfolio_id):
    from app.services.portfolio_service import get_portfolio_summary
    from app.services.pipeline.event_reads import event_records
    s = get_portfolio_summary(db, user, portfolio_id)
    facts = []
    def add(text, source):
        fid = f"f{len(facts) + 1}"; facts.append({"id": fid, "text": text, "source": source}); return fid
    total = float(s.total_value)
    add(f"Portfolio '{s.portfolio.name}' value {total:,.0f}, day change {float(s.day_change):+,.0f} ({_pct(s.day_change_percent)}%), cash {float(s.cash_balance):,.0f}; "
        f"prices dated {s.data_freshness_date} from {s.data_source}.", "stored holdings and database prices")
    for h in sorted(s.holdings, key=lambda h: -float(h.market_value))[:10]:
        w = float(h.market_value) / total * 100 if total else None
        add(f"Holding {h.symbol} ({h.sector}): weight {_pct(w)}%, day change {_pct(h.day_change_percent)}%, unrealized {_pct(h.unrealized_gain_loss_percent)}%.",
            f"holding {h.symbol}, price dated {h.latest_price_date}")
    holdings = sorted(s.holdings, key=lambda h: -float(h.market_value))
    if total and holdings:
        add(f"Concentration: cash is {_pct(float(s.cash_balance) / total * 100)}% of value; the top three holdings ({', '.join(h.symbol for h in holdings[:3])}) "
            f"are {_pct(sum(float(h.market_value) for h in holdings[:3]) / total * 100)}% of value.", "stored holdings and database prices")
        sectors = {}
        for h in holdings:
            sectors[h.sector] = sectors.get(h.sector, 0.0) + float(h.market_value) / total * 100
        add("Sector weights: " + "; ".join(f"{k} {v:.1f}%" for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])[:4]) + ".", "stored holdings and database prices")
    moves = [h for h in holdings if h.day_change is not None]
    if moves and float(s.day_change):
        lead = max(moves, key=lambda h: abs(float(h.day_change)))
        add(f"Largest contributor to the latest session's change: {lead.symbol} ({lead.sector}) contributed {float(lead.day_change):+,.0f} of the portfolio's {float(s.day_change):+,.0f}; "
            f"{sum(1 for h in moves if float(h.day_change) > 0)} holdings rose and {sum(1 for h in moves if float(h.day_change) < 0)} fell.", f"holding {lead.symbol}, price dated {lead.latest_price_date}")
    from app.services.market_service import get_market_overview
    snap = get_market_overview(db).snapshot
    if snap is not None and s.day_change_percent is not None:
        add(f"Benchmark {snap.index_name} moved {_pct(snap.index_change_percent)}% on its latest snapshot ({snap.snapshot_date}); the portfolio moved {_pct(s.day_change_percent)}%, "
            f"a gap of {_pct(float(s.day_change_percent) - float(snap.index_change_percent))} points.", f"market snapshot {snap.snapshot_date} ({snap.source})")
    if s.unpriced_symbols:
        add("No stored price for: " + ", ".join(s.unpriced_symbols) + ".", "valuation note")
    symbols = [h.symbol for h in s.holdings]
    events = event_records(db, symbols=symbols, window_days=30, limit=6) if symbols else []
    for e in events:
        linked = [x['subject_key'] for x in e['subjects'] if x['subject_key'] in symbols]
        add(f"Event ({str(e['occurred_at'])[:10]}, {e['materiality']}) affecting {', '.join(linked) or 'holdings'}: {e['title']}", "classified event " + e['event_key'])
    key_inputs = {"fresh": str(s.data_freshness_date), "holdings": sorted(f"{h.symbol}:{h.quantity}" for h in s.holdings),
                  "cash": str(s.cash_balance), "events": [e['event_key'] for e in events]}
    return facts, key_inputs


def company_facts(db, symbol):
    from app.services.market_service import get_company_detail
    from app.services.pipeline.event_reads import event_records
    from app.services.company_snapshot import financial_rows
    from app.services.research_intelligence_service import resolve_company
    detail = get_company_detail(db, symbol)
    facts = []
    def add(text, source):
        fid = f"f{len(facts) + 1}"; facts.append({"id": fid, "text": text, "source": source}); return fid
    c, p = detail.company, detail.latest_price
    if p:
        add(f"{c.symbol} ({c.name}, sector {c.sector}) closed at {float(p.close):,.2f}, change {_pct(p.change_percent)}%, volume {p.volume:,}, dated {p.trade_date}.",
            f"market prices {p.trade_date}")
        if p.market_cap:
            add(f"Reported market capitalization {float(p.market_cap):,.0f} PKR.", f"capitalization {p.trade_date}")
    instrument = resolve_company(db, symbol)
    latest = {}
    for r in financial_rows(db, instrument):
        key = r['metric']
        if key not in latest or r['period_end'] > latest[key]['period_end']:
            latest[key] = r
    for r in sorted(latest.values(), key=lambda r: r['metric'])[:12]:
        add(f"{r['metric'].replace('_', ' ')} was {float(r['value']):,.2f} {r['currency'] or r['unit'] or ''} for the {r['period_type']} period ending {r['period_end']} ({r['accounting_basis']}).".replace("  ", " "),
            f"filed financials, {r.get('source_name') or 'source label unavailable'}")
    events = event_records(db, symbols=[c.symbol], window_days=120, limit=5)
    for e in events:
        add(f"Event ({str(e['occurred_at'])[:10]}, {e['materiality']}): {e['title']}", "classified event " + e['event_key'])
    key_inputs = {"price": str(p.trade_date) if p else None, "close": str(p.close) if p else None,
                  "fin": sorted(f"{r['metric']}:{r['period_end']}" for r in latest.values()), "events": [e['event_key'] for e in events]}
    return facts, key_inputs


def _gather(db, user, scope, key):
    if scope == 'company':
        return company_facts(db, key)
    return market_facts(db) if scope == 'market' else portfolio_facts(db, user, key)


def _view(row):
    return {"brief": json.loads(row.brief_json) if row and row.brief_json else None,
            "facts": json.loads(row.facts_json) if row and row.facts_json else [],
            "generated_at": row.generated_at if row else None, "provider": row.provider if row else None, "model": row.model if row else None}


def read(db, user, scope, key="", *, schedule, retry=False):
    """Return the cached brief; call schedule(user_id, scope, key, hash) at most once if a new hash needs generating."""
    config = generation_config(db, user)
    rows = list(db.scalars(select(AIBrief).where(AIBrief.user_id == user.id, AIBrief.scope == scope, AIBrief.scope_key == key)
        .order_by(AIBrief.generated_at.desc())))
    previous = next((r for r in rows if r.status == 'ready'), None)
    if scope == 'portfolio':
        from app.services.portfolio_service import get_portfolio_or_404
        get_portfolio_or_404(db, user, key)
    pending = next((row for row in rows if row.status == 'running' and config
                    and row.provider == config['provider'] and row.model == config['model']
                    and utc(row.generated_at) >= datetime.now(UTC) - RUNNING_TTL), None)
    if pending and not retry:
        # Poll the existing generation, rather than rebuilding its facts on every GET.
        # Its next read after completion recomputes the input hash before marking it current.
        return {"status": "generating", "current": False, "error_code": None, **_view(previous)}
    facts, inputs = _gather(db, user, scope, key)
    h = fingerprint({"v": VERSION, "scope": scope, "key": key, "inputs": inputs, "cfg": config or {}})
    current = next((r for r in rows if r.input_hash == h), None)
    if current and current.status == 'ready':
        return {"status": "ready", "current": True, **_view(current)}
    status = 'provider_unavailable' if not config else 'not_generated'
    if config and not facts:
        status = 'no_data'
    elif config:
        stale_run = current and current.status == 'running' and utc(current.generated_at) < datetime.now(UTC) - RUNNING_TTL
        if current is None or stale_run or (retry and current.status == 'failed'):
            if current is not None:
                db.delete(current); db.commit()
            try:
                db.add(AIBrief(user_id=user.id, input_hash=h, scope=scope, scope_key=key, provider=config['provider'],
                               model=config['model'], status='running'))
                db.commit()
                schedule(user.id, scope, key, h)
                status = 'generating'
            except IntegrityError:
                db.rollback(); status = 'generating'
        else:
            status = 'generating' if current.status == 'running' else 'failed'
    out = _view(previous)
    return {"status": status, "current": False, "error_code": current.error_code if current else None, **out}


def _valid(raw, ids, symbols=frozenset()):
    data = json.loads(raw)
    sections = []
    for sec in data.get("sections", []):
        if not isinstance(sec, dict) or not sec.get("body"):
            continue
        fact_ids = [i for i in sec.get("fact_ids", []) if i in ids]
        if not fact_ids:
            continue
        sections.append({"title": str(sec.get("title", "")).strip()[:60], "body": str(sec["body"]).strip(),
                         "question": str(sec.get("question", "")).strip()[:160], "fact_ids": fact_ids,
                         "tickers": [t for t in dict.fromkeys(str(t).upper() for t in sec.get("tickers", [])) if t in symbols][:4]})
    if not data.get("headline") or not sections:
        raise ValueError("invalid_model_output")
    return {"headline": str(data["headline"])[:160], "summary": str(data.get("summary", "")).strip(),
            "sections": sections[:4], "events": [str(e) for e in data.get("events", [])][:3]}


async def generate(user_id, scope, key, h):
    """Generate once per owner/input without holding DB connections during inference."""
    identity = (user_id, scope, key, h)
    if identity in _inflight:
        return
    _inflight.add(identity)
    row_id = None
    try:
        from app.models.user import User
        from app.services.llm_key_service import get_decrypted_key_for_call
        from app.ai.providers.registry import get_provider
        from app.ai.providers.base import ProviderCallOptions
        with SessionLocal() as db:
            row = db.scalar(select(AIBrief).where(AIBrief.user_id == user_id, AIBrief.input_hash == h,
                                                 AIBrief.scope == scope, AIBrief.scope_key == key))
            if not row or not db.get(User, user_id):
                return
            row_id, provider, model = row.id, row.provider, row.model
        try:
            facts, _ = await asyncio.to_thread(lambda: _gather_sync(user_id, scope, key))
            messages = [{"role": "system", "content": PORTFOLIO_SYSTEM if scope == 'portfolio' else COMPANY_SYSTEM if scope == 'company' else SYSTEM},
                        {"role": "user", "content": "FACTS\n" + canonical(facts)}]
            symbols = set(re.findall(r'\b[A-Z][A-Z0-9]{1,9}\b', ' '.join(f['text'] for f in facts)))
            brief = None
            for attempt in range(2):
                with SessionLocal() as db:
                    api_key, _ = get_decrypted_key_for_call(db, db.get(User, user_id), provider)
                try:
                    result = await get_provider(provider).chat_with_options(api_key, messages, model,
                        options=ProviderCallOptions(json_mode=True, max_output_tokens=1400, deadline_seconds=60))
                finally:
                    api_key = None
                brief = _valid(result.content, {f["id"] for f in facts}, symbols)
                if not _too_numeric(brief):
                    break
                messages = messages[:2] + [{"role": "assistant", "content": result.content}, {"role": "user", "content":
                    "That draft restates figures. Rewrite it as analysis: no figures in the headline or titles, at most one figure per body, "
                    "interpret what is driving the picture and what it means for the reader, and leave the numbers to the ticker chips. Return the same JSON."}]
            with SessionLocal() as db:
                row = db.get(AIBrief, row_id)
                if row:
                    row.brief_json, row.facts_json, row.status = json.dumps(brief), json.dumps(facts), 'ready'
                    row.generated_at = datetime.now(UTC)
                    db.commit()
        except Exception as exc:
            log.warning("brief generation failed scope=%s: %s", scope, type(exc).__name__)
            with SessionLocal() as db:
                row = db.get(AIBrief, row_id)
                if row:
                    row.status = 'failed'
                    row.error_code = 'invalid_model_output' if isinstance(exc, (ValueError, KeyError)) else 'provider_request_failed'
                    db.commit()
    finally:
        _inflight.discard(identity)


def _gather_sync(user_id, scope, key):
    from app.models.user import User
    with SessionLocal() as db:
        return _gather(db, db.get(User, user_id), scope, key)
