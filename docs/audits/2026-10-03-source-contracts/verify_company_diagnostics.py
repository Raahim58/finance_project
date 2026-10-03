"""Read-only supplementary company diagnostics; run in the deployed API."""
import json
from datetime import UTC, datetime
from sqlalchemy import text
from app.db.session import SessionLocal

queries = {
    'error_totals': "select dataset_type,error_class,count(*) units from ingestion_coverage where status='failed' group by dataset_type,error_class",
    'partial_diagnostics': "select dataset_type,left(diagnostics_json,350) diagnostics,count(*) units from ingestion_coverage where status='partial' group by dataset_type,left(diagnostics_json,350) order by count(*) desc limit 10",
    'report_association': "select count(*) reports,count(*) filter(where company_id is null) without_company_id,count(*) filter(where symbol is not null) with_symbol,count(distinct symbol) symbols from documents where document_type in ('annual_report','quarterly_report','interim_report')",
    'active_reports_by_symbol': "select count(distinct c.symbol) active_with_reports from companies c join documents d on d.symbol=c.symbol where c.is_active and d.document_type in ('annual_report','quarterly_report','interim_report')",
    'future_periods': "select 'standardized' kind,count(*) rows,count(distinct instrument_id) instruments from standardized_financial_facts where period_end > current_date union all select 'filing',count(*),count(distinct instrument_id) from financial_facts where period_end > current_date",
    'partial_fundamentals_samples': "select i.symbol,c.diagnostics_json from ingestion_coverage c join instruments i on i.id=c.instrument_id where c.dataset_type='standardized_fundamentals' and c.status='partial' order by i.symbol limit 8",
}
with SessionLocal() as db:
    db.execute(text('SET TRANSACTION READ ONLY'))
    for key, query in queries.items():
        print(json.dumps(dict(check=key, checked_at=datetime.now(UTC), rows=[dict(row) for row in db.execute(text(query)).mappings()]), default=str), flush=True)
