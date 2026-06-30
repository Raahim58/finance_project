from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.portfolio import (
    HoldingCreate,
    HoldingResponse,
    HoldingUpdate,
    PortfolioCreate,
    PortfolioExposureResponse,
    PortfolioPerformancePoint,
    PortfolioResponse,
    PortfolioRiskFlagsResponse,
    PortfolioSummaryResponse,
    PortfolioUpdate,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)
from app.services.portfolio_service import (
    add_holding,
    add_transaction,
    create_portfolio,
    delete_holding,
    delete_portfolio,
    delete_transaction,
    get_portfolio_exposure,
    get_portfolio_or_404,
    get_portfolio_performance,
    get_portfolio_risk_flags,
    get_portfolio_summary,
    list_holdings,
    list_portfolios,
    list_transactions,
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    delete_portfolio(db, current_user, portfolio_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
