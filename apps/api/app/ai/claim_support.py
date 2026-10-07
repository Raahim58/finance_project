"""Deterministic source-scope and recorded financial-value checks.

These checks do not claim general prose entailment. Exact financial placeholders
are rendered from delivered SQL observations, never model arithmetic.
"""
import re
from decimal import Decimal, InvalidOperation
from app.tools.registry import expand_model_data

FACT_TOKEN = re.compile(r'\{\{fact:(E\d+):([a-z_]+):([0-9-]+|none):(standalone|consolidated|none)\}\}')
FINANCIAL_TERMS = re.compile(r'\b(revenue|sales|profit|income|eps|earnings per share|cash|assets?|liabilities|equity|borrowings|dividends?|payouts?|par value|face value)\b', re.I)
NUMBER = re.compile(r'(?<![\w-])[-+]?\d[\d,]*(?:\.\d+)?(?![\w-])')
SCALE = {'thousand': Decimal(1000), 'million': Decimal(1000000), 'billion': Decimal(1000000000)}
METRIC_LABELS = {
    'revenue': ('revenue', 'sales', 'turnover'), 'gross_revenue': ('gross revenue', 'gross sales'),
    'net_revenue': ('net revenue', 'net sales'), 'gross_profit': ('gross profit',),
    'ebit': ('operating profit', 'operating income'),
    'net_income': ('net income', 'net profit', 'profit after tax', 'profit'),
    'net_profit': ('net profit', 'profit'), 'cash': ('cash',),
    'assets': ('assets',), 'liabilities': ('liabilities',), 'equity': ('equity',),
    'debt': ('debt', 'borrowings'), 'earnings_per_share': ('earnings per share', 'eps'),
    'eps': ('eps',), 'dividend_per_share': ('dividend', 'dividends', 'payout'),
    'dividend_percent': ('dividend', 'dividends', 'payout'),
    'reported_dividend_per_share': ('dividend', 'dividends', 'payout'),
    'par_value_before': ('par value', 'face value'), 'par_value_after': ('par value', 'face value'),
}


def amount_metrics(prose, position):
    labels = [(match.start(), len(label), metric) for metric, aliases in METRIC_LABELS.items()
              for label in aliases for match in re.finditer(r'(?<!\w)'+re.escape(label)+r'(?!\w)', prose, re.I)]
    labels = [row for row in labels if not any(other[0] <= row[0] and other[0]+other[1] >= row[0]+row[1]
                                               and other[1] > row[1] for other in labels)]
    before = [row for row in labels if row[0] <= position]
    if before:
        start = max(row[0] for row in before)
        candidates = [row for row in before if row[0] == start]
    elif labels:
        start = min(row[0] for row in labels)
        candidates = [row for row in labels if row[0] == start]
    else:
        return set()
    longest = max(row[1] for row in candidates)
    return {row[2] for row in candidates if row[1] == longest}


def financial_observations(data, mapping, default_scope):
    """Bind typed SQL facts to their supplied record refs before model projection."""
    observations = []
    def visit(value, scope):
        if isinstance(value, list):
            for row in value: visit(row, scope)
        elif isinstance(value, dict):
            scope = {**scope, **{key: value[key] for key in ('instrument_id', 'symbol', 'accounting_basis') if value.get(key)}}
            if value.get('basis') in ('standalone', 'consolidated'):
                scope['accounting_basis'] = value['basis']
            if value.get('metric') and value.get('value') is not None:
                refs = value.get('evidence_refs') or value.get('source_refs') or []
                if not refs and value.get('id'):
                    refs = [value['id']]
                for ref in refs:
                    marker = mapping.get(ref)
                    if marker:
                        observations.append((marker, {**scope, **{key: value.get(key) for key in (
                            'metric', 'value', 'unit', 'currency', 'period_start', 'period_end', 'accounting_basis')
                            if value.get(key) is not None}}))
            # Only validated SQL statement records have kind + lifecycle +
            # source refs. Ordinary RAG chunks never enter this numeric path.
            if value.get('kind') in ('reported_fact', 'management_claim', 'guidance') and value.get('lifecycle'):
                statement = value.get('text', '')
                amounts = re.findall(r'\bdividend\b[^.!?]{0,120}?\b(Rs\.?|PKR)\s*([\d,]+(?:\.\d+)?)\s*per share\b', statement, re.I)
                if not re.search(r'\bdividends? (?:received|receivable|income)\b|\bsubsidiar\w*\b', statement, re.I):
                    for ref in value.get('evidence_refs', []):
                        if ref in mapping:
                            for currency, amount in amounts:
                                observations.append((mapping[ref], {**scope, 'metric': 'reported_dividend_per_share',
                                    'value': amount.replace(',', ''), 'unit': currency.rstrip('.')+'/share',
                                    'kind': value['kind'], 'lifecycle': value['lifecycle'],
                                    'source_date': value.get('published_date')}))
            if 'dividend' in str(value.get('type', '')) and value.get('source_backed'):
                details = value.get('details') or {}
                for field, metric, unit in [('payout_percent', 'dividend_percent', 'percent_of_par'),
                                            ('cash_per_share', 'dividend_per_share', 'PKR/share')]:
                    if details.get(field) is None: continue
                    for ref in value.get('evidence_refs', []):
                        if ref in mapping:
                            observations.append((mapping[ref], {**scope, 'metric': metric, 'value': details[field],
                                'unit': unit, 'period_end': value.get('effective_date')}))
            if value.get('type') == 'stock_split' and value.get('source_backed'):
                details = value.get('details') or {}
                faces = re.fullmatch(r'Rs\.\s*(\d+(?:\.\d+)?)/- to Rs\.\s*(\d+(?:\.\d+)?)/-', str(details.get('ratio_evidence', '')))
                if faces and details.get('verification') == 'source_reviewed':
                    for ref in value.get('evidence_refs', []):
                        if ref in mapping:
                            for index, metric in [(1, 'par_value_before'), (2, 'par_value_after')]:
                                observations.append((mapping[ref], {**scope, 'metric': metric, 'value': faces[index],
                                    'unit': 'PKR/share', 'period_end': value.get('effective_date')}))
            for child in value.values():
                if isinstance(child, (dict, list)): visit(child, scope)
    visit(expand_model_data(data), default_scope)
    return observations


def render_financial_placeholders(answer, evidence):
    errors = []
    def replace(match):
        ref, metric, period, basis = match.groups()
        records = (evidence.get(ref) or {}).get('observations', [])
        selected = [row for row in records if row.get('metric') == metric
                    and str(row.get('period_end') or 'none') == period
                    and str(row.get('accounting_basis') or 'none') == basis]
        # Conflicting values for the same selector remain unavailable.
        identities = {(str(row.get('value')), row.get('unit'), row.get('currency'), row.get('period_start')) for row in selected}
        if not selected or len(identities) != 1 or not selected[0].get('unit'):
            errors.append({'code': 'financial_selector_unavailable', 'reference': ref, 'metric': metric})
            return '[financial value unavailable]'
        row = selected[0]
        details = ', '.join(value for value in (
            None if basis == 'none' else basis,
            None if period == 'none' else 'period ended '+period,
            row.get('lifecycle') if row.get('metric') == 'reported_dividend_per_share' else None) if value)
        return f"{row['value']} {row['unit']}" + (f" ({details})" if details else '') + f' [[{ref}]]'
    return FACT_TOKEN.sub(replace, answer), errors


def scope_errors(answer, evidence, marker_pattern, identity):
    known_symbols = {source.get('symbol') for item in evidence.values() if (source := item['source']).get('symbol')}
    for row in [*(identity.get('mentioned_instrument_candidates') or []), *(identity.get('portfolio_instruments') or []), identity.get('explicit_instrument') or {}]:
        if row.get('symbol'): known_symbols.add(row['symbol'])
    errors = []
    for line in re.split(r'\n|(?<=[.!?])\s+(?=[A-Z])', answer):
        matches = list(marker_pattern.finditer(line))
        refs = [ref.strip() for match in matches for ref in match.group(1).split(',')]
        if not refs: continue
        sources = [evidence[ref]['source'] for ref in refs if ref in evidence]
        subjects = {symbol for symbol in known_symbols if re.search(r'(?<!\w)'+re.escape(symbol)+r'(?!\w)', line)}
        scoped = {source.get('symbol') for source in sources if source.get('symbol')}
        # Unscoped sector/portfolio text may legitimately describe many issuers.
        # Only a fully scoped citation set can establish an issuer mismatch.
        if subjects and scoped and all(source.get('symbol') for source in sources) and not subjects <= scoped:
            errors.append({'code': 'citation_issuer_mismatch', 'subjects': sorted(subjects), 'references': refs})
    return errors


def numeric_errors(answer, evidence, marker_pattern):
    """Check inline financial amounts against typed cited records, including units.

    Dates and explicitly labelled growth/ratios are outside this amount check.
    Their calculations keep their existing tool provenance; this is not full
    natural-language numerical entailment.
    """
    errors = []
    for line in re.split(r'\n|(?<=[.!?])\s+(?=[A-Z])', answer):
        if not FINANCIAL_TERMS.search(line): continue
        matches = list(marker_pattern.finditer(line))
        refs = [ref.strip() for match in matches for ref in match.group(1).split(',')]
        if not refs: continue
        records = [row for ref in refs for row in (evidence.get(ref) or {}).get('observations', [])]
        prose = marker_pattern.sub('', line)
        prose = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', prose)
        prose = re.sub(r'^\s*\d+[.)]\s*', '', prose)
        for match in NUMBER.finditer(prose):
            trailing = prose[match.end():]
            metrics = amount_metrics(prose, match.start())
            percentage = bool(re.match(r'\s*(?:%|percent)', trailing, re.I))
            if percentage and re.search(r'\bdividend yield\b', prose, re.I):
                metrics = {'dividend_yield'}
            if percentage and not metrics & {'dividend_per_share', 'reported_dividend_per_share', 'dividend_percent', 'dividend_yield'}: continue
            if re.match(r'\s*(?:years?\b|months?\b|days?\b)', trailing, re.I): continue
            if len(match.group().replace(',', '')) == 4 and match.group().isdigit() and 1900 <= int(match.group()) <= 2100:
                continue
            scale_match = re.match(r'\s*(thousand|million|billion)\b', trailing, re.I)
            scale = SCALE[scale_match[1].lower()] if scale_match else Decimal(1)
            value = Decimal(match.group().replace(',', ''))*scale
            decimals = len(match.group().split('.', 1)[1]) if '.' in match.group() else 0
            tolerance = scale*Decimal(10)**(-decimals)/2
            supported = False
            for row in records:
                try:
                    if metrics and row.get('metric') not in metrics: continue
                    if row.get('lifecycle') in ('proposed', 'unknown', 'cancelled') and re.search(r'\b(paid|received|credited)\b', prose, re.I): continue
                    unit = str(row.get('unit', '')).lower()
                    if percentage != (unit == 'percent_of_par' or (row.get('metric') == 'dividend_yield' and unit in ('%', 'percent'))): continue
                    stored_scale = next((factor for word, factor in SCALE.items() if word in unit), Decimal(1))
                    stored = Decimal(str(row['value']))*stored_scale
                    if abs(stored-value) <= tolerance:
                        supported = True; break
                except (InvalidOperation, KeyError): continue
            if not supported:
                errors.append({'code': 'financial_amount_unsupported', 'amount': match.group(), 'references': refs})
    return errors
