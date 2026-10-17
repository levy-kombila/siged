"""API Rayonnage : localisation physique des exemplaires papier (site › salle › rayonnage › travée › tablette › boîte)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, require
from app.core.security import Perm
from app.models import Document, ShelfKind, ShelfLocation
from app.schemas import DocumentLocationIn, DocumentOut, ShelfLocationIn, ShelfLocationOut
from app.services import audit

router = APIRouter(prefix="/api/shelving", tags=["Rayonnage"])
doc_router = APIRouter(prefix="/api/documents", tags=["Rayonnage"])


def _counts(db: Session) -> dict[int, int]:
    return dict(db.execute(select(Document.shelf_location_id, func.count(Document.id))
                           .where(Document.shelf_location_id.is_not(None))
                           .group_by(Document.shelf_location_id)).all())


def _node(n: ShelfLocation, counts: dict[int, int]) -> dict:
    children = [_node(c, counts) for c in sorted(n.children, key=lambda c: c.code)]
    direct = counts.get(n.id, 0)
    return {"id": n.id, "code": n.code, "label": n.label, "kind": n.kind, "capacity": n.capacity,
            "description": n.description, "path": n.path, "documents": direct,
            "total_documents": direct + sum(c["total_documents"] for c in children), "children": children}


@router.get("", summary="Arborescence du rayonnage avec occupation")
def tree(db: Session = Depends(get_db), _: Principal = Depends(require(Perm.DOC_READ))):
    nodes = db.execute(select(ShelfLocation)).scalars().all()
    counts = _counts(db)
    return [_node(n, counts) for n in sorted(nodes, key=lambda n: n.code) if n.parent_id is None]


@router.get("/kinds", summary="Niveaux de localisation disponibles")
def kinds(_: Principal = Depends(require(Perm.DOC_READ))):
    return ShelfKind.ALL


@router.get("/flat", response_model=list[ShelfLocationOut])
def flat(db: Session = Depends(get_db), _: Principal = Depends(require(Perm.DOC_READ))):
    return db.execute(select(ShelfLocation).order_by(ShelfLocation.code)).scalars().all()


def _check_parent(db: Session, data: ShelfLocationIn, self_id: int | None = None):
    if data.parent_id is None:
        return
    node = db.get(ShelfLocation, data.parent_id)
    if not node:
        raise HTTPException(422, "Emplacement parent introuvable")
    if ShelfKind.ALL.index(node.kind) >= ShelfKind.ALL.index(data.kind):
        raise HTTPException(422, f"Un niveau {data.kind} ne peut pas être placé dans un niveau {node.kind}")
    while node:  # empêche les cycles
        if node.id == self_id:
            raise HTTPException(422, "Cycle dans le rayonnage")
        node = node.parent


@router.post("", response_model=ShelfLocationOut, status_code=201)
def create(data: ShelfLocationIn, db: Session = Depends(get_db), p: Principal = Depends(require(Perm.SHELVING_MANAGE))):
    if db.execute(select(ShelfLocation.id).where(ShelfLocation.code == data.code)).first():
        raise HTTPException(409, "Code déjà utilisé")
    _check_parent(db, data)
    node = ShelfLocation(**data.model_dump())
    db.add(node)
    db.flush()
    audit.log(db, p.actor, "SHELF_CREATE", "shelf_location", str(node.id), data.model_dump())
    return node


@router.put("/{loc_id}", response_model=ShelfLocationOut)
def update(loc_id: int, data: ShelfLocationIn, db: Session = Depends(get_db),
           p: Principal = Depends(require(Perm.SHELVING_MANAGE))):
    node = db.get(ShelfLocation, loc_id)
    if not node:
        raise HTTPException(404, "Emplacement introuvable")
    if db.execute(select(ShelfLocation.id).where(ShelfLocation.code == data.code, ShelfLocation.id != loc_id)).first():
        raise HTTPException(409, "Code déjà utilisé")
    _check_parent(db, data, loc_id)
    for k, v in data.model_dump().items():
        setattr(node, k, v)
    audit.log(db, p.actor, "SHELF_UPDATE", "shelf_location", str(node.id), data.model_dump())
    return node


@router.delete("/{loc_id}", status_code=204)
def delete(loc_id: int, db: Session = Depends(get_db), p: Principal = Depends(require(Perm.SHELVING_MANAGE))):
    node = db.get(ShelfLocation, loc_id)
    if not node:
        raise HTTPException(404, "Emplacement introuvable")
    if node.children or db.execute(select(Document.id).where(Document.shelf_location_id == loc_id).limit(1)).first():
        raise HTTPException(409, "Emplacement non vide (sous-niveaux ou documents rangés)")
    db.delete(node)
    audit.log(db, p.actor, "SHELF_DELETE", "shelf_location", str(loc_id), {"code": node.code})


@router.get("/{loc_id}/documents", response_model=list[DocumentOut], summary="Documents rangés à cet emplacement")
def documents(loc_id: int, db: Session = Depends(get_db), _: Principal = Depends(require(Perm.DOC_READ))):
    if not db.get(ShelfLocation, loc_id):
        raise HTTPException(404, "Emplacement introuvable")
    return db.execute(select(Document).where(Document.shelf_location_id == loc_id)
                      .order_by(Document.reference)).unique().scalars().all()


@doc_router.put("/{doc_id}/location", response_model=DocumentOut, summary="Ranger l'exemplaire papier (ou le retirer)")
def set_location(doc_id: str, data: DocumentLocationIn, db: Session = Depends(get_db),
                 p: Principal = Depends(require(Perm.SHELVING_MANAGE))):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document introuvable")
    old = {"location": doc.shelf_location.path if doc.shelf_location else None, "physical_ref": doc.physical_ref}
    loc = None
    if data.shelf_location_id is not None:
        loc = db.get(ShelfLocation, data.shelf_location_id)
        if not loc:
            raise HTTPException(422, "Emplacement introuvable")
        if loc.capacity and loc.id != doc.shelf_location_id:
            used = db.execute(select(func.count(Document.id)).where(Document.shelf_location_id == loc.id)).scalar_one()
            if used >= loc.capacity:
                raise HTTPException(409, f"Emplacement plein ({used}/{loc.capacity})")
    doc.shelf_location_id = loc.id if loc else None
    doc.physical_ref = data.physical_ref.strip()
    audit.log(db, p.actor, "DOCUMENT_LOCATION", "document", doc.id,
              {"old": old, "new": {"location": loc.path if loc else None, "physical_ref": doc.physical_ref}},
              commit=False)
    db.commit()
    db.refresh(doc)
    return doc
