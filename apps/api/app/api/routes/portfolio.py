from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.portfolio import (
    AllocationSetCreate,
    AllocationSetResponse,
    CashBalanceResponse,
    HoldingCreate,
    HoldingResponse,
    HoldingUpdate,
    PortfolioCreate,
    PortfolioDuplicateRequest,
    PortfolioExposureResponse,
    PortfolioPerformancePoint,
    PortfolioResponse,
    PortfolioRiskFlagsResponse,
    PortfolioSummaryResponse,
    PortfolioUpdate,
    PositionResponse,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)
from app.schemas.event_intelligence import PortfolioEventsResponse
from app.services.event_intelligence_service import portfolio_event_exposure
from app.services.portfolio_service import (
    add_holding,
    add_transaction,
    archive_portfolio,
    create_allocation_set,
    create_portfolio,
    delete_holding,
    delete_portfolio,
    delete_transaction,
    duplicate_portfolio,
    get_cash,
    get_portfolio_exposure,
    get_portfolio_or_404,
    get_portfolio_performance,
    get_portfolio_risk_flags,
    get_portfolio_summary,
    get_positions,
    list_allocation_sets,
    list_holdings,
    list_portfolios,
    list_transactions,
    restore_portfolio,
    select_default_portfolio,
    serialize_portfolio,
    update_holding,
    update_portfolio,
    update_transaction,
)

router = APIRouter()


@router.get("", response_model=list[PortfolioResponse])
def get_portfolios(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[PortfolioResponse]:
    return list_portfolios(db, current_user)


@router.post("", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
def post_portfolio(
    payload: PortfolioCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortfolioResponse:
    return create_portfolio(db, current_user, payload)


@router.get("/compare")
def compare_portfolios(
    portfolio_ids: list[str] = Query(..., min_length=2, max_length=10),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "portfolios": [
            get_portfolio_summary(db, current_user, portfolio_id).model_dump(mode="json")
            for portfolio_id in portfolio_ids
        ]
    }


@router.get("/{portfolio_id}", response_model=PortfolioResponse)
def get_portfolio(
    portfolio_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortfolioResponse:
    return serialize_portfolio(get_portfolio_or_404(db, current_user, portfolio_id))


@router.patch("/{portfolio_id}", response_model=PortfolioResponse)
def patch_portfolio(
    portfolio_id: str,
    payload: PortfolioUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortfolioResponse:
    return update_portfolio(db, current_user, portfolio_id, payload)


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_portfolio(
    portfolio_id: str,
    confirm: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    delete_portfolio(db, current_user, portfolio_id, confirmed=confirm)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{portfolio_id}/duplicate", response_model=PortfolioResponse, status_code=201)
def duplicate(portfolio_id: str, payload: PortfolioDuplicateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return duplicate_portfolio(db, current_user, portfolio_id, payload)


@router.post("/{portfolio_id}/archive", response_model=PortfolioResponse)
def archive(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return archive_portfolio(db, current_user, portfolio_id)


@router.post("/{portfolio_id}/restore", response_model=PortfolioResponse)
def restore(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return restore_portfolio(db, current_user, portfolio_id)


@router.post("/{portfolio_id}/select-default", response_model=PortfolioResponse)
def select_default(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return select_default_portfolio(db, current_user, portfolio_id)


@router.get("/{portfolio_id}/positions", response_model=list[PositionResponse])
def positions(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_positions(db, current_user, portfolio_id)


@router.get("/{portfolio_id}/cash", response_model=CashBalanceResponse)
def cash(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_cash(db, current_user, portfolio_id)


@router.get("/{portfolio_id}/allocations", response_model=list[AllocationSetResponse])
def allocations(portfolio_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_allocation_sets(db, current_user, portfolio_id)


@router.post("/{portfolio_id}/allocations", response_model=AllocationSetResponse, status_code=201)
def create_allocation(portfolio_id: str, payload: AllocationSetCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return create_allocation_set(db, current_user, portfolio_id, payload)


@router.get("/{portfolio_id}/summary", response_model=PortfolioSummaryResponse)
def portfolio_summary(
    portfolio_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortfolioSummaryResponse:
    return get_portfolio_summary(db, current_user, portfolio_id)


@router.get("/{portfolio_id}/exposure", response_model=PortfolioExposureResponse)
def portfolio_exposure(
    portfolio_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortfolioExposureResponse:
    return get_portfolio_exposure(db, current_user, portfolio_id)


@router.get("/{portfolio_id}/events", response_model=PortfolioEventsResponse)
def portfolio_events(
    portfolio_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortfolioEventsResponse:
    return PortfolioEventsResponse.model_validate(
        portfolio_event_exposure(db, current_user, portfolio_id, limit=limit)
    )


@router.get("/{portfolio_id}/performance", response_model=list[PortfolioPerformancePoint])
def portfolio_performance(
    portfolio_id: str,
    limit: int = 90,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PortfolioPerformancePoint]:
    return get_portfolio_performance(db, current_user, portfolio_id, limit=limit)


@router.get("/{portfolio_id}/risk-flags", response_model=PortfolioRiskFlagsResponse)
def portfolio_risk_flags(
    portfolio_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortfolioRiskFlagsResponse:
    return get_portfolio_risk_flags(db, current_user, portfolio_id)


@router.get("/{portfolio_id}/holdings", response_model=list[HoldingResponse])
def get_holdings(
    portfolio_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[HoldingResponse]:
    return list_holdings(db, current_user, portfolio_id)


@router.post("/{portfolio_id}/holdings", response_model=HoldingResponse, status_code=status.HTTP_201_CREATED)
def post_holding(
    portfolio_id: str,
    payload: HoldingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HoldingResponse:
    return add_holding(db, current_user, portfolio_id, payload)


@router.patch("/holdings/{holding_id}", response_model=HoldingResponse)
def patch_holding(
    holding_id: str,
    payload: HoldingUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HoldingResponse:
    return update_holding(db, current_user, holding_id, payload)


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_holding(
    holding_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    delete_holding(db, current_user, holding_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{portfolio_id}/transactions", response_model=list[TransactionResponse])
def get_transactions(
    portfolio_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TransactionResponse]:
    return list_transactions(db, current_user, portfolio_id)


@router.post("/{portfolio_id}/transactions", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
def post_transaction(
    portfolio_id: str,
    payload: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionResponse:
    return add_transaction(db, current_user, portfolio_id, payload)


@router.patch("/transactions/{transaction_id}", response_model=TransactionResponse)
def patch_transaction(
    transaction_id: str,
    payload: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionResponse:
    return update_transaction(db, current_user, transaction_id, payload)


@router.delete("/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_transaction(
    transaction_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    delete_transaction(db, current_user, transaction_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
    AllocationSetCreate,
    AllocationSetResponse,
    CashBalanceResponse,
    archive_portfolio,
    create_allocation_set,
    duplicate_portfolio,
    get_cash,
    get_positions,
    list_allocation_sets,
    restore_portfolio,
    select_default_portfolio,
