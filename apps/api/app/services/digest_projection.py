"""Select retained evidence before compact encoding; never truncate source text."""
import copy
from app.domain.evidence_query import dividend_query
from app.services.pipeline.statements import labels
from app.services.pipeline.intelligence import EVENT_SECTIONS

SECTION_FIELDS = {
    'financial_performance': ('financials', 'changes', 'conflicts'),
    'earnings_drivers': ('financials', 'changes', 'conflicts'),
    'dividends': ('corporate_actions', 'financials'),
    'expansion': ('disclosures',),
    'material_developments': ('disclosures',),
    'sector_macro': ('sector', 'macro'),
    'risks': ('risk',),
    'unresolved_questions': (),
}


def retained_refs(value):
    refs = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('source_ref', 'ref') and isinstance(item, str):
                refs.add(item)
            elif key in ('source_refs', 'evidence_refs', 'refs') and isinstance(item, list):
                refs.update(ref for ref in item if isinstance(ref, str))
            else:
                refs.update(retained_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(retained_refs(item))
    return refs


def select_digest_evidence(snapshot, requested_sections):
    if requested_sections is None:
        return copy.deepcopy(snapshot)
    selected = set(requested_sections)
    fields = {field for section in selected for field in SECTION_FIELDS[section]}
    result = {key: copy.deepcopy(value) for key, value in snapshot.items()
              if key in fields or key in ('version', 'company', 'input_hash')}
    if 'financials' in result and not selected & {'financial_performance', 'earnings_drivers'}:
        result['financials'] = [row for row in result['financials']
                                if dividend_query(row.get('metric', '').replace('_', ' '))]
    if 'corporate_actions' in result:
        result['corporate_actions'] = [row for row in result['corporate_actions']
                                      if 'dividend' in str(row.get('type', '')).lower()]
    news = []
    for row in snapshot.get('news', []):
        text = row.get('text', '')
        _, event, _ = labels(text)
        section = 'dividends' if dividend_query(text) else EVENT_SECTIONS.get(event, 'material_developments')
        if section in selected or (row.get('lane') in ('sector', 'broader') and 'sector_macro' in selected):
            news.append(copy.deepcopy(row))
    result['news'] = news
    refs = retained_refs(result)
    result['sources'] = {ref: copy.deepcopy(source) for ref, source in snapshot.get('sources', {}).items() if ref in refs}
    result['coverage'] = {'requested_sections': list(requested_sections),
                          'omitted_snapshot_fields': sorted(set(snapshot)-set(result)-{'sources', 'size', 'coverage', 'missing_data'}),
                          'detail_tools': ['research.company_sections', 'research.search']}
    result['missing_data'] = [copy.deepcopy(gap) for gap in snapshot.get('missing_data', [])
                              if gap.get('section') in fields or gap.get('section') in selected]
    return result
