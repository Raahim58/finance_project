from fastapi import APIRouter

from app.api.routes import assistant_workspace, assistant, auth, documents, health, ingestion, intelligence, market, monitoring, portfolio, rag, research, settings, workstation

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
api_router.include_router(assistant_workspace.router, tags=["assistant"])
api_router.include_router(intelligence.router, tags=["intelligence"])
api_router.include_router(monitoring.router, tags=["monitoring"])
from app.api.routes import portfolio_build_extras
api_router.include_router(portfolio_build_extras.router, tags=["portfolio build"])

from app.api.routes import portfolio_scenarios_extras
api_router.include_router(portfolio_scenarios_extras.router, tags=["portfolio scenarios"])

from app.api.routes import research_intelligence
api_router.include_router(research_intelligence.router, tags=["research intelligence"])
