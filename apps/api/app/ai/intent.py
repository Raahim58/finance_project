import re


INTENT_PATTERNS = (
    ("security_fit", re.compile(r"worth adding|interesting right now|fit my portfolio|risks? of|contradict", re.I)),
    ("decision_request", re.compile(r"what (?:should|can) i do|what do you recommend|recommendation|next (?:step|action)|how (?:should|can) i improve", re.I)),
    ("risk_concentration", re.compile(r"risk.*concentrat|concentrat.*risk|where.*risk|riskiest|risk contribut|biggest risk", re.I)),
    ("compliance", re.compile(r"\bmandate\b|\bcompliance\b|\bips\b|\bbreach\b|\bconstraint\b|\bviolat", re.I)),
    ("scenario", re.compile(r"\bscenario\b|stress test|\bshock\b|what if|hypothetical", re.I)),
    ("performance", re.compile(r"perform|\breturn\b|attribut|sharpe|\balpha\b|\bcagr\b|drawdown|tracking error|\bbeta\b", re.I)),
    ("market_overview", re.compile(r"market (overview|breadth)|\bfreshness\b|\bstale\b|market.wide|how is the market|market status", re.I)),
    ("holding_evidence", re.compile(r"\bfiling|management|\bcompany\b|\bholding\b|position in|\bstock\b|\bevidence\b|\bdocument", re.I)),
)
NARRATIVE_TRIGGER_RE = re.compile(r"\bwhy\b|what changed|\bfiling|\bmanagement\b|\bevent|contradict", re.I)


def detect_intent(question: str) -> str:
    for intent, pattern in INTENT_PATTERNS:
        if pattern.search(question):
            return intent
    return "generic"
