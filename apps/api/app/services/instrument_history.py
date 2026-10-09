"""Only a sourced, reviewed listing date can bound a historical request."""
from datetime import date
import json


def history_start(instrument, requested: date) -> date:
    try:
        metadata = json.loads(instrument.metadata_json or "{}")
    except (ValueError, TypeError):
        metadata = {}
    url = metadata.get("listing_date_source_url")
    verified = metadata.get("listing_date_verified") is True and isinstance(url, str) and url.startswith(("https://", "http://"))
    # Older DPS ingestion populated active_from with catalog-discovery dates.
    # Their presence alone does not prove a listing date.
    return max(requested, instrument.active_from) if verified and instrument.active_from else requested
