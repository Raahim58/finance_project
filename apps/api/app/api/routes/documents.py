from datetime import date

from fastapi import APIRouter, Depends, File, Form, Path, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.rag import DocumentResponse
from app.services.rag_service import get_document, ingest_upload, list_documents

router = APIRouter()


@router.get("", response_model=list[DocumentResponse])
def documents(
    symbol: str | None = None,
    document_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    order: str = Query(default="added", pattern="^(added|published)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentResponse]:
    return list_documents(db, current_user, symbol=symbol, document_type=document_type, limit=limit, order=order)


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    document_type: str = Form(...),
    symbol: str | None = Form(default=None),
    sector: str | None = Form(default=None),
    fiscal_year: int | None = Form(default=None),
    quarter: str | None = Form(default=None),
    source_name: str = Form(default="manual"),
    source_url: str | None = Form(default=None),
    published_date: date | None = Form(default=None),
    visibility: str = Form(default="private", pattern="^(public|private)$"),
    portfolio_id: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    return await ingest_upload(
        db,
        file,
        title=title,
        document_type=document_type,
        symbol=symbol,
        sector=sector,
        fiscal_year=fiscal_year,
        quarter=quarter,
        source_name=source_name,
        source_url=source_url,
        published_date=published_date,
        user=current_user,
        visibility=visibility,
        portfolio_id=portfolio_id,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def document(document_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentResponse:
    return get_document(db, current_user, document_id)


@router.get("/{document_id}/pages/{page_number}")
def page(document_id: str, page_number: int = Path(ge=1),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.research_evidence_service import document_page
    return document_page(db, current_user, document_id, page_number)
