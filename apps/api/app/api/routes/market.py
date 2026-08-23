from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.market import (
    CompanyDetailResponse,
    CompanyResponse,
    MarketFreshnessResponse,
    MarketOverviewResponse,
    MarketPriceResponse,
    MarketSnapshotResponse,
    SectorDailyStatsResponse,
)
from app.services.market_service import (
    get_company_detail,
    get_company_history,
    get_market_freshness,
    get_market_snapshot,
    get_sectors,
    get_sector_performance,
    get_top_gainers,
    get_top_losers,
    get_top_volume,
    search_companies,
)

router = APIRouter()


@router.get("/freshness", response_model=MarketFreshnessResponse)
def freshness(db: Session = Depends(get_db)):
    return get_market_freshness(db)


@router.get("/snapshot", response_model=MarketSnapshotResponse | None)
def snapshot(date_: date | None = Query(default=None, alias="date"), db: Session = Depends(get_db)):
    return get_market_snapshot(db, date_)


@router.get("/overview", response_model=MarketOverviewResponse)
def overview(date_: date | None = Query(default=None, alias="date"), db: Session = Depends(get_db)):
    return MarketOverviewResponse(
        snapshot=get_market_snapshot(db, date_),
        top_gainers=get_top_gainers(db, date_, limit=5),
        top_losers=get_top_losers(db, date_, limit=5),
        top_volume=get_top_volume(db, date_, limit=5),
        sectors=get_sectors(db, date_),
    )


@router.get("/top-gainers", response_model=list[MarketPriceResponse])
def top_gainers(
    date_: date | None = Query(default=None, alias="date"),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return get_top_gainers(db, date_, limit)


@router.get("/top-losers", response_model=list[MarketPriceResponse])
def top_losers(
    date_: date | None = Query(default=None, alias="date"),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return get_top_losers(db, date_, limit)


@router.get("/top-volume", response_model=list[MarketPriceResponse])
def top_volume(
    date_: date | None = Query(default=None, alias="date"),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return get_top_volume(db, date_, limit)


@router.get("/sectors", response_model=list[SectorDailyStatsResponse])
def sectors(date_: date | None = Query(default=None, alias="date"), db: Session = Depends(get_db)):
    return get_sectors(db, date_)


@router.get("/sectors/{sector}/performance", response_model=list[SectorDailyStatsResponse])
def sector_performance(
    sector: str,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    return get_sector_performance(db, sector, start_date, end_date)


@router.get("/companies", response_model=list[CompanyResponse])
def companies(
    q: str | None = None,
    limit: int = Query(default=1000, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return search_companies(db, q, limit)


@router.get("/company/{symbol}", response_model=CompanyDetailResponse)
def company(symbol: str, db: Session = Depends(get_db)):
    return get_company_detail(db, symbol)


@router.get("/company/{symbol}/history", response_model=list[MarketPriceResponse])
def company_history(
    symbol: str,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=2000, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    return get_company_history(db, symbol, start_date, end_date, limit)
