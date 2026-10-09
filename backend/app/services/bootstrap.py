"""Initialisation : rôles RBAC, compte administrateur, plan de classement par défaut."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import DEFAULT_ROLES, hash_password
from app.models import Role, User
from app.services.classification import seed_plan

logger = logging.getLogger("siged.bootstrap")


def seed(db: Session) -> None:
    for name, (desc, perms) in DEFAULT_ROLES.items():
        role = db.execute(select(Role).where(Role.name == name)).scalar()
        if not role:
            db.add(Role(name=name, description=desc, permissions=list(perms)))
        else:
            role.permissions = list(perms)  # synchronise les droits avec le code
    db.commit()
    s = get_settings()
    if not db.execute(select(User.id).limit(1)).first():
        admin_role = db.execute(select(Role).where(Role.name == "admin")).scalar_one()
        db.add(User(username=s.bootstrap_admin_username, email=s.bootstrap_admin_email,
                    full_name="Administrateur SIGED", hashed_password=hash_password(s.bootstrap_admin_password),
                    role_id=admin_role.id))
        db.commit()
        logger.warning("Compte administrateur initial créé (%s) : changez le mot de passe !",
                       s.bootstrap_admin_username)
    seed_plan(db)
