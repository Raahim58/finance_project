"""SQL eligibility for public financial context; observed is not reviewed."""
from sqlalchemy import and_, false, func, not_, or_, select

from app.models.document import Document
from app.models.workstation import FinancialFact, StandardizedFinancialFact


def public_primary_financials():
    documents=select(Document.id).where(Document.visibility=='public',
        Document.owner_user_id.is_(None),Document.portfolio_id.is_(None),
        Document.status.not_in(('revoked','superseded','failed')),
        Document.data_status.not_in(('synthetic_demo','excluded_irrelevant')))
    label = func.lower(func.coalesce(FinancialFact.source_label, ""))
    # A citation cannot make a misclassified tax deduction into revenue, or a
    # dividend receipt into a cash balance. Keep the source observations stored
    # but fail closed when their own label contradicts their taxonomy.
    contradiction = or_(
        and_(FinancialFact.taxonomy_key == "revenue",
             or_(label.like("%sales tax%"), label.like("%excise duty%"))),
        and_(FinancialFact.taxonomy_key == "cash", label.like("%dividend receipt%")),
        and_(FinancialFact.taxonomy_key.in_(("assets", "liabilities", "equity", "debt")),
             FinancialFact.value < 0),
    )
    return and_(or_(FinancialFact.document_id.is_(None),FinancialFact.document_id.in_(documents)),
                not_(contradiction))


def verified_secondary_financials():
    """Fail closed until a reviewed period/unit/basis contract exists.

    The legacy table has a period label and unit string but stores no verified
    fiscal calendar, reporting basis or period duration. Changing its quality
    status alone cannot make it suitable for exact current financial context.
    Original observations remain in SQL and the unverified research display.
    """
    return false()


def secondary_financial_gap(db,instrument_id):
    count=db.scalar(select(func.count()).select_from(StandardizedFinancialFact).where(
        StandardizedFinancialFact.instrument_id==instrument_id,
        StandardizedFinancialFact.quality_status.not_in(('rejected','superseded')))) or 0
    if not count: return None
    return {'code':'unverified_secondary_financials','row_count':count,
        'missing':['verified_fiscal_period','accounting_basis','period_duration','reporting_unit_validation'],
        'detail':'Legacy secondary observations remain stored; their dates, units and reporting basis require source review before use as verified financial values or calculation inputs.'}
