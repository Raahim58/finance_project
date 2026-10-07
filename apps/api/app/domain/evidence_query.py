"""Question-specific document retrieval policy; never supplies numerical facts."""
import re
from datetime import date, timedelta

DIVIDENDS = re.compile(r'\b(dividends?|payouts?|cash distributions?|shareholder (?:income|payments?|returns?))\b', re.I)
DIVIDEND_SUPPORT = re.compile(r'\b(sustainab\w*|afford\w*|coverage|cover|cash flows?|earnings|rates?|inflation|risks?)\b', re.I)
ALTERNATIVES = re.compile(
    r'\b(?:better|stronger|more attractive|higher yielding|safer) (?:stocks?|shares?|companies|options?|investments?)\b|'
    r'\balternatives?\b|\boutside\b|\bother (?:stocks?|shares?|companies|names|options)\b|'
    r'\bwhat else\b|\bnew (?:stocks?|positions?|ideas?)\b|\binstead\b|\bbeyond\b|'
    r'\bdiversify into\b|\bredeploy (?:my |the )?capital\b', re.I)


def dividend_query(query: str) -> bool:
    percentage_explanation = bool(re.search(r'%|\bpercent(?:age)?\b', query, re.I)
        and re.search(r'\b(against|wdym|mean|par|face value)\b', query, re.I)
        and not re.search(r'\b(return|growth|risk|volatility|weight|tax|inflation|allocation)\b', query, re.I))
    return bool(DIVIDENDS.search(query)) or percentage_explanation


def shareholder_payout_passage(text: str) -> bool:
    """Dividend receipts by the business are a different information need."""
    if not dividend_query(text): return False
    received = re.search(r'\bdividend(?:s)? (?:income|received|receivable)\b', text, re.I)
    declared = re.search(r'\b(?:per share|interim dividend|final dividend|declared|proposed|recommended|announced|shareholders?)\b', text, re.I)
    return not received or bool(declared)


def search_policy(payload):
    """Preserve explicit filters. Add dates only for explicit freshness requests."""
    query = payload.query
    purpose = ('investment_income' if re.search(r'\b(?:subsidiar\w*|associates?|dividend income|dividends? received)\b', query, re.I)
               else 'dividends') if dividend_query(query) else 'general'
    broader = payload.include_broader_context
    if purpose == 'dividends':
        broader = broader and bool(DIVIDEND_SUPPORT.search(query))
        query = DIVIDENDS.sub('dividend', query)
    start, end = payload.date_from, payload.date_to
    if start is None and end is None:
        days = 0 if re.search(r'\btoday\b', query, re.I) else 7 if re.search(r'\b(?:this|last|past) week\b', query, re.I) else 30 if re.search(r'\b(recent\w*|lately|latest news)\b', query, re.I) else None
        if days is not None:
            end = date.today(); start = end-timedelta(days=days)
    return payload.model_copy(update={'query': query, 'include_broader_context': broader,
                                     'date_from': start, 'date_to': end}), purpose
