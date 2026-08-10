from fastapi import APIRouter

from app.api.routes import assistant, auth, documents, health, ingestion, market, monitoring, portfolio, rag, research, settings, workstation

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(market.router, prefix="/market", tags=["market"])
api_router.include_router(portfolio.router, prefix="/portfolios", tags=["portfolios"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(rag.router, prefix="/rag", tags=["rag"])
api_router.include_router(workstation.router, tags=["workstation"])
api_router.include_router(research.router, tags=["research"])
api_router.include_router(ingestion.router, tags=["ingestion"])
api_router.include_router(assistant.router, tags=["assistant"])
api_router.include_router(monitoring.router, tags=["monitoring"])
