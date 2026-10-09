"""Plan de classement : arborescence métier normée + classement automatique par règles."""
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ClassificationNode

# Plan de classement de démonstration (inspiré des plans types des administrations)
DEFAULT_PLAN = [
    # code, libellé, parent, DUA, sort final, types, mots-clés
    ("ADM", "Administration générale", None, None, None, [], []),
    ("ADM.01", "Courrier et correspondance", "ADM", 5, "DESTROY", ["courrier", "lettre", "note"], ["courrier", "correspondance"]),
    ("ADM.02", "Procès-verbaux et comptes rendus", "ADM", 10, "ARCHIVE", ["pv", "compte-rendu"], ["proces-verbal", "reunion", "compte rendu"]),
    ("RH", "Ressources humaines", None, None, None, [], []),
    ("RH.01", "Dossiers individuels du personnel", "RH", 50, "ARCHIVE", ["contrat", "dossier-personnel"], ["contrat de travail", "matricule", "embauche"]),
    ("RH.02", "Paie", "RH", 10, "DESTROY", ["bulletin-paie"], ["bulletin de paie", "salaire", "paie"]),
    ("FIN", "Finances et comptabilité", None, None, None, [], []),
    ("FIN.01", "Factures fournisseurs", "FIN", 10, "DESTROY", ["facture"], ["facture", "fournisseur"]),
    ("FIN.02", "Budget", "FIN", 10, "ARCHIVE", ["budget"], ["budget", "loi de finances"]),
    ("JUR", "Affaires juridiques", None, None, None, [], []),
    ("JUR.01", "Contrats et conventions", "JUR", 30, "ARCHIVE", ["convention", "marche"], ["convention", "marche public", "avenant"]),
]


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").replace("_", " ").split())


def seed_plan(db: Session) -> None:
    if db.execute(select(ClassificationNode.id).limit(1)).first():
        return
    by_code: dict[str, ClassificationNode] = {}
    for code, label, parent, dua, sort, types, kws in DEFAULT_PLAN:
        node = ClassificationNode(code=code, label=label, parent=by_code.get(parent) if parent else None,
                                  default_dua_years=dua, default_final_disposition=sort,
                                  rule_doc_types=types, rule_keywords=kws)
        db.add(node)
        by_code[code] = node
    db.commit()


def auto_classify(db: Session, doc_type: str, keywords: list[str], title: str, text: str = "") -> ClassificationNode | None:
    """Score simple et explicable : type de document = 10 pts, mot-clé de règle trouvé
    dans les mots-clés / le titre = 3 pts, dans le texte extrait = 1 pt."""
    t = normalize(doc_type)
    kw_blob = " | ".join(normalize(k) for k in keywords) + " | " + normalize(title)
    text_blob = normalize(text[:20000])
    best, best_score = None, 0
    for node in db.execute(select(ClassificationNode)).scalars():
        score = 0
        if t and t in [normalize(x) for x in node.rule_doc_types or []]:
            score += 10
        for rk in node.rule_keywords or []:
            rk = normalize(rk)
            if rk and rk in kw_blob:
                score += 3
            elif rk and text_blob and rk in text_blob:
                score += 1
        if score > best_score:
            best, best_score = node, score
    return best


def descendants_ids(db: Session, node_id: int) -> list[int]:
    ids, frontier = [node_id], [node_id]
    while frontier:
        children = db.execute(select(ClassificationNode.id).where(
            ClassificationNode.parent_id.in_(frontier))).scalars().all()
        ids += children
        frontier = children
    return ids


def build_tree(nodes: list[ClassificationNode]) -> list[dict]:
    by_parent: dict[int | None, list[ClassificationNode]] = {}
    for n in nodes:
        by_parent.setdefault(n.parent_id, []).append(n)

    def rec(pid):
        return [{"id": n.id, "code": n.code, "label": n.label, "default_dua_years": n.default_dua_years,
                 "default_final_disposition": n.default_final_disposition,
                 "rule_doc_types": n.rule_doc_types, "rule_keywords": n.rule_keywords,
                 "children": rec(n.id)} for n in sorted(by_parent.get(pid, []), key=lambda x: x.code)]
    return rec(None)
