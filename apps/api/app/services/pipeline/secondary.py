"""Secondary provider evidence remains quarantined until period/unit/basis review."""
import json
from app.providers.fundamentals.scstrade_tables import ScsTradeTablesProvider
from app.services.ingestion_persistence import source,store_artifact


def capture(db,symbol, *, provider=None):
    provider=provider or ScsTradeTablesProvider()
    publisher=source(db,'SCSTrade secondary financial tables','standardized_financials','https://www.scstrade.com',40,None,
        'Issuer-isolated public table captures. Units, fiscal periods and reporting basis require validation before numerical promotion.')
    ids=[]
    for table in provider.fetch(symbol):
        artifact=store_artifact(db,publisher,table.content,url=table.request_url,method='POST',
            parser_version=provider.parser_version,content_type=table.content_type,
            request_scope={'symbol':symbol,'table':table.table,'parameters':table.request_scope})
        artifact.status='needs_review'
        artifact.response_metadata_json=json.dumps({**json.loads(artifact.response_metadata_json),
            'issuer_session':symbol,'accounting_basis':'unverified','reporting_units':'unverified','classification':'standardized_secondary'})
        ids.append(artifact.id)
    return {'artifacts':ids,'status':'needs_review','gap':'Secondary units, fiscal periods, issuer response and basis require review; no canonical facts written.'}
