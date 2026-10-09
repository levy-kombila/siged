"""Moteur de recherche : critères de métadonnées + plein texte.

* PostgreSQL : to_tsvector('french', ...) @@ websearch_to_tsquery (index GIN), classement
  ts_rank et extrait surligné ts_headline ; recherche floue sur le titre (pg_trgm).
* SQLite (dev / tests) : repli ILIKE.
"""
import time
from datetime import date

from sqlalchemy import String, and_, cast, func, literal, or_, select
from sqlalchemy.orm import Session

from app.models import DocStatus, Document, DocumentMetadata, DocumentVersion
from app.services.classification import descendants_ids

SORTS = {
    "date_desc": Document.document_date.desc(),
    "date_asc": Document.document_date.asc(),
    "title": Document.title.asc(),
    "created_desc": Document.created_at.desc(),
}


def search(db: Session, *, q: str | None = None, title: str | None = None, author: str | None = None,
           doc_type: str | None = None, keyword: str | None = None, status: str | None = None,
           classification_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
           meta_key: str | None = None, meta_value: str | None = None, reference: str | None = None,
           include_disposed: bool = False, sort: str = "relevance", page: int = 1, size: int = 20) -> dict:
    t0 = time.perf_counter()
    pg = db.get_bind().dialect.name == "postgresql"
    cv = DocumentVersion
    stmt = select(Document).outerjoin(cv, and_(cv.document_id == Document.id, cv.is_current.is_(True)))
    conds = []
    score = literal(0.0)
    snippet = literal(None)

    if q:
        if pg:
            tsv = func.to_tsvector("french", func.coalesce(cv.extracted_text, ""))
            tsq = func.websearch_to_tsquery("french", q)
            conds.append(or_(tsv.op("@@")(tsq), Document.title.ilike(f"%{q}%"),
                             Document.description.ilike(f"%{q}%")))
            score = func.ts_rank(tsv, tsq) + func.similarity(Document.title, q)
            snippet = func.ts_headline("french", func.coalesce(cv.extracted_text, ""), tsq,
                                       "MaxWords=30, MinWords=10, StartSel=<mark>, StopSel=</mark>")
        else:
            like = f"%{q}%"
            conds.append(or_(cv.extracted_text.ilike(like), Document.title.ilike(like),
                             Document.description.ilike(like)))
            score = literal(1.0)
    if title:
        conds.append(Document.title.ilike(f"%{title}%"))
    if author:
        conds.append(Document.author.ilike(f"%{author}%"))
    if reference:
        conds.append(Document.reference == reference)
    if doc_type:
        conds.append(Document.doc_type == doc_type.lower())
    if keyword:
        # mots-clés stockés en JSON : recherche textuelle portable
        conds.append(cast(Document.keywords, String).ilike(f'%{keyword}%'))
    if status:
        conds.append(Document.status == status)
    elif not include_disposed:
        conds.append(Document.status != DocStatus.DESTROYED)
    if classification_id:
        conds.append(Document.classification_id.in_(descendants_ids(db, classification_id)))
    if date_from:
        conds.append(Document.document_date >= date_from)
    if date_to:
        conds.append(Document.document_date <= date_to)
    if meta_key:
        sub = select(DocumentMetadata.document_id).where(DocumentMetadata.meta_key == meta_key)
        if meta_value:
            sub = sub.where(DocumentMetadata.meta_value.ilike(f"%{meta_value}%"))
        conds.append(Document.id.in_(sub))

    if conds:
        stmt = stmt.where(*conds)
    total = db.execute(select(func.count()).select_from(stmt.with_only_columns(Document.id).subquery())).scalar()

    ordered = stmt.add_columns(score.label("score"), snippet.label("snippet"))
    if sort == "relevance" and q:
        ordered = ordered.order_by(score.desc(), Document.document_date.desc())
    else:
        ordered = ordered.order_by(SORTS.get(sort, Document.document_date.desc()))
    size = max(1, min(size, 100))
    page = max(1, page)
    rows = db.execute(ordered.offset((page - 1) * size).limit(size)).unique().all()
    items = []
    for doc, sc, snip in rows:
        if snip is None and q and doc.current_version and doc.current_version.extracted_text:
            snip = _snippet(doc.current_version.extracted_text, q)
        items.append((doc, float(sc) if sc is not None else None, snip))
    return {"total": total, "page": page, "size": size,
            "took_ms": round((time.perf_counter() - t0) * 1000, 2), "items": items}


def _snippet(text: str, q: str, width: int = 120) -> str | None:
    low = text.lower()
    for term in q.lower().split():
        i = low.find(term)
        if i >= 0:
            start = max(0, i - width // 2)
            frag = text[start:start + width]
            return ("…" if start else "") + frag.replace(text[i:i + len(term)], f"<mark>{text[i:i + len(term)]}</mark>") + "…"
    return None
