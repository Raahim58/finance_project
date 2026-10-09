"""Cached AI market and portfolio briefs.

Facts come only from database queries. Page reads never call the model: a brief is served from cache
until its input hash changes (new trading day, market close, a new classified event, changed holdings),
and then one background generation is started for that hash. Failed hashes are not retried automatically.
"""
import asyncio, json, logging
from datetime import UTC, datetime, timedelta
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.db.session import SessionLocal
from app.domain.research_relevance import canonical, fingerprint, utc
from app.models.research_intelligence import AIBrief
from app.services.research_job_service import generation_config

log = logging.getLogger(__name__)
VERSION = 'brief.v1'
RUNNING_TTL = timedelta(minutes=5)
_inflight: set[str] = set()

SYSTEM = (
    "You write a short brief for a Pakistan Stock Exchange investor from FACTS only. Never use outside knowledge, "
    "never invent numbers, causes or forecasts, and give no trade instructions. Every bullet must cite the fact ids it "
    "relies on. If facts are thin, say what is missing. Return JSON: {\"headline\": str (<=110 chars), "
    "\"summary\": str (2-3 sentences), \"points\": [{\"text\": str, \"fact_ids\": [str]}] (3-6 items), "
    "\"watch\": [str] (0-3 items: missing data or things to check)}."
)


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


def _gather(db, user, scope, key):
    return market_facts(db) if scope == 'market' else portfolio_facts(db, user, key)


def _view(row):
    return {"brief": json.loads(row.brief_json) if row and row.brief_json else None,
            "facts": json.loads(row.facts_json) if row and row.facts_json else [],
            "generated_at": row.generated_at if row else None, "provider": row.provider if row else None, "model": row.model if row else None}


def read(db, user, scope, key="", *, schedule, retry=False):
    """Return the cached brief; call schedule(user_id, scope, key, hash) at most once if a new hash needs generating."""
    config = generation_config(db, user)
    facts, inputs = _gather(db, user, scope, key)
    h = fingerprint({"v": VERSION, "scope": scope, "key": key, "inputs": inputs, "cfg": config or {}})
    rows = list(db.scalars(select(AIBrief).where(AIBrief.user_id == user.id, AIBrief.scope == scope, AIBrief.scope_key == key)
        .order_by(AIBrief.generated_at.desc())))
    current = next((r for r in rows if r.input_hash == h), None)
    previous = next((r for r in rows if r.status == 'ready'), None)
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


def _valid(raw, ids):
    data = json.loads(raw)
    points = [{"text": str(p["text"]).strip(), "fact_ids": [i for i in p.get("fact_ids", []) if i in ids]}
              for p in data.get("points", []) if isinstance(p, dict) and p.get("text")]
    points = [p for p in points if p["fact_ids"]]
    if not data.get("headline") or not data.get("summary") or not points:
        raise ValueError("invalid_model_output")
    return {"headline": str(data["headline"])[:160], "summary": str(data["summary"]),
            "points": points[:6], "watch": [str(w) for w in data.get("watch", [])][:3]}


async def generate(user_id, scope, key, h):
    """Background task: one provider call, validated against the fact ids, stored under the input hash."""
    if h in _inflight:
        return
    _inflight.add(h)
    try:
        from app.models.user import User
        from app.services.llm_key_service import get_decrypted_key_for_call
        from app.ai.providers.registry import get_provider
        from app.ai.providers.base import ProviderCallOptions
        with SessionLocal() as db:
            user = db.get(User, user_id)
            row = db.scalar(select(AIBrief).where(AIBrief.user_id == user_id, AIBrief.input_hash == h, AIBrief.scope == scope, AIBrief.scope_key == key))
            if not row or not user:
                return
            try:
                facts, _ = await asyncio.to_thread(lambda: _gather_sync(user_id, scope, key))
                messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "FACTS\n" + canonical(facts)}]
                api_key, _rec = get_decrypted_key_for_call(db, user, row.provider)
                result = await get_provider(row.provider).chat_with_options(api_key, messages, row.model,
                    options=ProviderCallOptions(json_mode=True, max_output_tokens=1200, deadline_seconds=60))
                api_key = None
                brief = _valid(result.content, {f["id"] for f in facts})
                row.brief_json, row.facts_json, row.status = json.dumps(brief), json.dumps(facts), 'ready'
                row.generated_at = datetime.now(UTC)
            except Exception as exc:
                log.warning("brief generation failed scope=%s: %s", scope, type(exc).__name__)
                row.status, row.error_code = 'failed', ('invalid_model_output' if isinstance(exc, (ValueError, KeyError)) else 'provider_request_failed')
            db.commit()
    finally:
        _inflight.discard(h)


def _gather_sync(user_id, scope, key):
    from app.models.user import User
    with SessionLocal() as db:
        return _gather(db, db.get(User, user_id), scope, key)
