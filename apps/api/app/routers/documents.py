"""Heritage document search + detail endpoints (spec FR-04 / §3.1 / §3.2).

* ``GET /v1/documents`` — keyword + facet search over the ingested
  heritage corpus. Returns a list of lightweight :class:`DocumentOut`
  rows (no original_text / modern_text bodies — those are big enough
  to dominate the payload and only the detail page renders them).
* ``GET /v1/documents/{id}`` — full document detail (spec §3.1 / §13):
  the classical Korean ``original_text``, the modern Korean
  ``modern_text`` translation, the metadata, **and** a structured
  KOGL-1 license notice with the pre-formatted "출처: ..."
  attribution string so the frontend can render the spec-mandated
  source line + license link inline.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.document import Document
from app.schemas.document import DocumentDetailOut, DocumentOut

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentOut])
def search_documents(
    q: str = "",
    institution: str | None = None,
    region: str | None = None,
    period: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    query = db.query(Document)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Document.title.ilike(like),
                Document.original_text.ilike(like),
                Document.summary.ilike(like),
            )
        )
    if institution:
        query = query.filter(Document.institution == institution)
    if region:
        query = query.filter(Document.region == region)
    if period:
        query = query.filter(Document.period == period)
    rows = query.order_by(Document.title.asc()).limit(min(limit, 50)).all()
    return [DocumentOut.model_validate(r) for r in rows]


@router.get("/{doc_id}", response_model=DocumentDetailOut)
def get_document(doc_id: str, db: Session = Depends(get_db)) -> DocumentDetailOut:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "DOCUMENT_NOT_FOUND",
                "message": "No document with that id.",
                "status": 404,
            },
        )
    return DocumentDetailOut.from_orm_model(doc)
