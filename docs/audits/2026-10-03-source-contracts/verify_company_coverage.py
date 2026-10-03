"""Read-only Oracle company coverage audit; no ingestion or queue writes."""
import json
from datetime import UTC, datetime
from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.market_providers import DpsMarketDataProvider
from app.providers.fundamentals.dps_standardized import DpsStandardizedFundamentalsProvider

def emit(check, rows):
    print(json.dumps(dict(check=check, checked_at=datetime.now(UTC), rows=rows), default=str), flush=True)

queries = {
    "price_sources": "select source,count(*) rows,count(distinct symbol) symbols,min(trade_date) earliest,max(trade_date) latest,count(*) filter(where market_cap is null) missing_market_cap from market_prices group by source",
    "active_price_coverage": "with p as(select company_id,count(*) n,max(trade_date) latest from market_prices group by company_id) select c.is_active,count(*) companies,count(*) filter(where p.n is null) no_prices,count(*) filter(where p.latest=(select max(trade_date) from market_prices)) on_latest_date from companies c left join p on p.company_id=c.id group by c.is_active",
    "instrument_coverage": "select c.is_active,count(*) companies,count(*) filter(where i.id is null) no_instrument,count(*) filter(where c.sector='Unknown') unknown_sector from companies c left join instruments i on i.company_id=c.id group by c.is_active",
    "coverage_states": "select dataset_type,status,count(*) units,count(distinct instrument_id) instruments,sum(item_count) items,min(attempted_at) first_attempt,max(attempted_at) last_attempt from ingestion_coverage group by dataset_type,status order by dataset_type,status",
    "coverage_errors": "select dataset_type,status,error_class,left(error_message,240) error,count(*) units from ingestion_coverage where error_class is not null group by dataset_type,status,error_class,left(error_message,240) order by count(*) desc limit 20",
    "standardized_facts": "select source,metric,count(*) rows,count(distinct instrument_id) instruments,max(period_end) latest_period,max(retrieved_at) last_retrieved from standardized_financial_facts group by source,metric order by source,metric",
    "financial_facts": "select taxonomy_key,count(*) rows,count(distinct instrument_id) instruments,max(period_end) latest_period from financial_facts group by taxonomy_key order by taxonomy_key",
    "active_other_coverage": "select count(*) active,count(*) filter(where exists(select 1 from standardized_financial_facts f where f.instrument_id=i.id)) with_standardized,count(*) filter(where exists(select 1 from financial_facts f where f.instrument_id=i.id)) with_filing_facts,count(*) filter(where exists(select 1 from documents d where d.company_id=c.id and d.document_type in ('annual_report','interim_report'))) with_reports,count(*) filter(where exists(select 1 from ingestion_coverage cv where cv.instrument_id=i.id and cv.dataset_type='standardized_fundamentals')) with_fundamentals_ledger from companies c left join instruments i on i.company_id=c.id where c.is_active",
    "screening": "select as_of_date,count(*) instruments,count(*) filter(where screenable) screenable,count(*) filter(where promoted) promoted,min(completeness) min_completeness,max(completeness) max_completeness from company_screening_snapshots group by as_of_date order by as_of_date desc limit 4",
    "documents": "select document_type,status,count(*) documents,count(distinct company_id) companies from documents group by document_type,status order by document_type,status",
    "canonical": "select count(*) observations,count(distinct instrument_id) instruments,count(*) filter(where is_selected) selected,count(distinct instrument_id) filter(where is_selected) selected_instruments,max(effective_at) latest from market_observations",
    "quality": "select rule,selection_status,count(*) issues from data_quality_issues group by rule,selection_status order by count(*) desc limit 15",
    "latest_run": "select mode,status,started_at,latest_trade_date,attempted_count,accepted_count,rejected_count,records_written,message from market_ingestion_runs order by started_at desc limit 5",
    "company_gaps": "select c.symbol,c.is_active,c.sector,i.instrument_type,(select count(*) from market_prices p where p.company_id=c.id) price_rows,(select max(trade_date) from market_prices p where p.company_id=c.id) latest_price,(select count(*) from standardized_financial_facts f where f.instrument_id=i.id) standardized_rows,(select count(*) from financial_facts f where f.instrument_id=i.id) filing_rows from companies c left join instruments i on i.company_id=c.id order by c.symbol",
}
with SessionLocal() as db:
    db.execute(text('SET TRANSACTION READ ONLY'))
    for key, query in queries.items():
        emit(key, [dict(row) for row in db.execute(text(query)).mappings()])

provider = DpsMarketDataProvider()
try:
    rows = provider.fetch_latest_prices()
    ordinary = {r['symbol'] for r in provider.observed_universe if not r.get('is_debt') and not r.get('is_etf') and not r.get('is_gem')}
    emit('live_dps_contract', dict(universe=len(provider.observed_universe), ordinary=len(ordinary), accepted=len(rows), trade_dates=sorted({r.trade_date for r in rows}), missing=sorted(ordinary-{r.symbol for r in rows}), quality_issues=provider.quality_issues, universe_rows=provider.observed_universe))
except Exception as exc:
    emit('live_dps_contract_error', dict(error_type=type(exc).__name__, message=str(exc)[:240]))
for symbol in ['HBL', 'ENGRO', 'AAL', 'AGLNCPS']:
    try:
        raw, facts, diagnostics, url = DpsStandardizedFundamentalsProvider().fetch(symbol)
        emit('live_fundamentals_sample', dict(symbol=symbol, url=url, raw_bytes=len(raw), fact_count=len(facts), metrics=sorted({f.metric for f in facts}), diagnostics=diagnostics))
    except Exception as exc:
        emit('live_fundamentals_sample', dict(symbol=symbol,error_type=type(exc).__name__,message=str(exc)[:240]))
