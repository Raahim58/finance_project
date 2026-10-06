"""Evidence identity is its underlying row/location, independent of presentation."""
import json
from hashlib import sha256

def source_identity(source):
    if source.get('underlying_id'):
        key=['underlying',source['underlying_id'],source.get('version'),source.get('as_of')]
    elif source.get('chunk_id'):
        key=['chunk',source['chunk_id']]
    elif source.get('document_id'):
        key=['document',source['document_id'],source.get('page_number'),source.get('quote_snippet')]
    elif source.get('artifact_id'):
        key=['artifact',source['artifact_id'],source.get('page_number'),source.get('effective_at') or source.get('as_of')]
    else:
        key=['source',source.get('source_url'),source.get('source_name') or source.get('source'),
             source.get('title'),source.get('page_number'),source.get('published_at') or source.get('as_of'),source.get('quote_snippet')]
    return sha256(json.dumps(key,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
