"""API Plan de classement."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, require
from app.core.security import Perm
from app.models import ClassificationNode, Document
from app.schemas import ClassificationIn, ClassificationOut
from app.services import audit
from app.services.classification import auto_classify, build_tree

router = APIRouter(prefix="/api/classification", tags=["Plan de classement"])


@router.get("", summary="Arborescence complète")
def tree(db: Session = Depends(get_db), _: Principal = Depends(require(Perm.DOC_READ))):
    return build_tree(db.execute(select(ClassificationNode)).scalars().all())


@router.get("/flat", response_model=list[ClassificationOut])
def flat(db: Session = Depends(get_db), _: Principal = Depends(require(Perm.DOC_READ))):
    return db.execute(select(ClassificationNode).order_by(ClassificationNode.code)).scalars().all()


class SuggestIn(BaseModel):
    doc_type: str = ""
    keywords: list[str] = []
    title: str = ""


@router.post("/suggest", response_model=ClassificationOut | None, summary="Proposer une rubrique (classement auto)")
def suggest(data: SuggestIn, db: Session = Depends(get_db), _: Principal = Depends(require(Perm.DOC_READ))):
    return auto_classify(db, data.doc_type, data.keywords, data.title)


def _check_parent(db: Session, parent_id: int | None, self_id: int | None = None):
    if parent_id is None:
        return
    node = db.get(ClassificationNode, parent_id)
    if not node:
        raise HTTPException(422, "Rubrique parente introuvable")
    while node:  # empêche les cycles
        if node.id == self_id:
            raise HTTPException(422, "Cycle dans le plan de classement")
        node = node.parent


@router.post("", response_model=ClassificationOut, status_code=201)
def create(data: ClassificationIn, db: Session = Depends(get_db),
           p: Principal = Depends(require(Perm.CLASSIFICATION_MANAGE))):
    if db.execute(select(ClassificationNode).where(ClassificationNode.code == data.code)).first():
        raise HTTPException(409, "Code déjà utilisé")
    _check_parent(db, data.parent_id)
    node = ClassificationNode(**data.model_dump())
    db.add(node)
    db.flush()
    audit.log(db, p.actor, "CLASSIFICATION_CREATE", "classification", str(node.id), data.model_dump())
    return node


@router.put("/{node_id}", response_model=ClassificationOut)
def update(node_id: int, data: ClassificationIn, db: Session = Depends(get_db),
           p: Principal = Depends(require(Perm.CLASSIFICATION_MANAGE))):
    node = db.get(ClassificationNode, node_id)
    if not node:
        raise HTTPException(404, "Rubrique introuvable")
    _check_parent(db, data.parent_id, node_id)
    for k, v in data.model_dump().items():
        setattr(node, k, v)
    audit.log(db, p.actor, "CLASSIFICATION_UPDATE", "classification", str(node.id), data.model_dump())
    return node


@router.delete("/{node_id}", status_code=204)
def delete(node_id: int, db: Session = Depends(get_db), p: Principal = Depends(require(Perm.CLASSIFICATION_MANAGE))):
    node = db.get(ClassificationNode, node_id)
    if not node:
        raise HTTPException(404, "Rubrique introuvable")
    if node.children or db.execute(select(Document.id).where(Document.classification_id == node_id).limit(1)).first():
        raise HTTPException(409, "Rubrique non vide (sous-rubriques ou documents rattachés)")
    db.delete(node)
    audit.log(db, p.actor, "CLASSIFICATION_DELETE", "classification", str(node_id), {"code": node.code})
