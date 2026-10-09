"""Evidence identity is its underlying row/location, independent of presentation."""
import json
from hashlib import sha256


INTERNAL_SOURCE_FIELDS = (
    'record_type', 'record_id', 'portfolio_id', 'instrument_id', 'ips_version_id',
    'verification_id', 'calculation_method', 'version', 'run_id', 'data_cutoff',
    'data_freshness_date', 'as_of', 'confirmed_at', 'annualization',
    'price_provenance', 'price_observations', 'price_source',
)


def source_identity(source):
    if source.get('underlying_id'):
        key=['underlying',source['underlying_id'],source.get('version'),source.get('as_of')]
    elif source.get('chunk_id'):
        key=['chunk',source['chunk_id']]
    elif source.get('document_id'):
        key=['document',source['document_id'],source.get('page_number'),source.get('quote_snippet')]
    elif source.get('artifact_id'):
        key=['artifact',source['artifact_id'],source.get('page_number'),source.get('effective_at') or source.get('as_of')]
    elif (
        any(source.get(field) for field in ('record_id', 'portfolio_id', 'instrument_id', 'verification_id'))
        and any(source.get(field) for field in ('record_type', 'calculation_method', 'verification_id'))
    ):
        # Private SQL evidence often has no public URL or title. Its display
        # label is shared across different portfolios and calculations; using
        # that label as identity silently replaces an earlier citation's method
        # and cutoff. Preserve only identities/versions actually supplied by
        # the tool, including its recorded price dependencies when available.
        key = ['internal_record', {
            field: source[field] for field in INTERNAL_SOURCE_FIELDS
            if source.get(field) is not None
        }]
    else:
        key=['source',source.get('source_url'),source.get('source_name') or source.get('source'),
             source.get('title'),source.get('page_number'),source.get('published_at') or source.get('as_of'),source.get('quote_snippet')]
    return sha256(json.dumps(key,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
