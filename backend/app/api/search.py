"""API de recherche (critères de métadonnées + plein texte)."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, require
from app.core.security import Perm
from app.schemas import SearchHit, SearchResult
from app.services import audit, search as svc

router = APIRouter(prefix="/api", tags=["Recherche"])


@router.get("/search", response_model=SearchResult, summary="Recherche avancée")
def search(q: str | None = Query(None, description="Plein texte (contenu OCR, titre, description)"),
           title: str | None = None, author: str | None = None, doc_type: str | None = None,
           keyword: str | None = None, status: str | None = None, classification_id: int | None = None,
           date_from: date | None = None, date_to: date | None = None, reference: str | None = None,
           meta_key: str | None = None, meta_value: str | None = None, include_disposed: bool = False,
           sort: str = Query("relevance", pattern="^(relevance|date_desc|date_asc|title|created_desc)$"),
           page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
           db: Session = Depends(get_db), p: Principal = Depends(require(Perm.DOC_READ))):
    res = svc.search(db, q=q, title=title, author=author, doc_type=doc_type, keyword=keyword, status=status,
                     classification_id=classification_id, date_from=date_from, date_to=date_to,
                     reference=reference, meta_key=meta_key, meta_value=meta_value,
                     include_disposed=include_disposed, sort=sort, page=page, size=size)
    criteria = {k: v for k, v in dict(q=q, title=title, author=author, doc_type=doc_type, keyword=keyword,
                                      status=status, classification_id=classification_id).items() if v}
    if criteria:
        audit.log(db, p.actor, "SEARCH", "search", None, {"criteria": criteria, "total": res["total"]})
    items = []
    for doc, score, snippet in res["items"]:
        hit = SearchHit.model_validate(doc)
        hit.score, hit.snippet = score, snippet
        items.append(hit)
    return SearchResult(total=res["total"], page=res["page"], size=res["size"], took_ms=res["took_ms"], items=items)
