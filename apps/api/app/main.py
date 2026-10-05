import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.db.session import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    from app.ai.token_counting import local_assets
    try:
        await asyncio.to_thread(local_assets)
    except (FileNotFoundError, ImportError):
        pass  # Explicit conservative fallback until tokenizer setup is run.
    # Load the existing local embedder before accepting questions. Its cold
    # initialization can exceed the unchanged research-tool deadline.
    from app.services.rag_service import embed_text
    try:
        await asyncio.to_thread(embed_text, "market financial evidence")
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Embedding startup preload failed (%s); retrieval will report availability normally",
            type(exc).__name__,
        )
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
    from app.services.assistant_execution import maintenance, shutdown
    task = asyncio.create_task(maintenance())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    return app


app = create_app()
