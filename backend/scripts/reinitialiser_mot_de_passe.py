"""Réinitialise le mot de passe d'un compte et lève son verrouillage.

À utiliser si le mot de passe administrateur est perdu, ou si le compte a été créé
avec un autre SIGED_BOOTSTRAP_ADMIN_PASSWORD lors d'un premier démarrage.

    Docker   : docker compose exec api python -m scripts.reinitialiser_mot_de_passe admin
    En local : python -m scripts.reinitialiser_mot_de_passe admin      (depuis backend/)

Le nouveau mot de passe est demandé deux fois (saisie masquée). L'opération est tracée
dans le journal d'audit.
"""
import getpass
import sys

from sqlalchemy import func, select

from app.core.database import SessionLocal, init_engine
from app.core.security import check_password_policy, hash_password
from app.models import User
from app.services import audit
from app.services.audit import Actor


def main() -> int:
    username = (sys.argv[1] if len(sys.argv) > 1 else "admin").strip().lower()
    init_engine()
    with SessionLocal() as db:
        user = db.execute(select(User).where(func.lower(User.username) == username)).scalar()
        if not user:
            names = ", ".join(db.execute(select(User.username)).scalars())
            print(f"Compte « {username} » introuvable. Comptes existants : {names or 'aucun'}")
            return 1
        pwd = getpass.getpass("Nouveau mot de passe : ")
        if pwd != getpass.getpass("Confirmez : "):
            print("Les deux saisies diffèrent.")
            return 1
        if err := check_password_policy(pwd):
            print(err)
            return 1
        user.hashed_password = hash_password(pwd)
        user.failed_logins = 0
        user.locked_until = None
        user.is_active = True
        audit.log(db, Actor(None, "system:cli"), "PASSWORD_RESET", "user", str(user.id),
                  {"username": user.username}, commit=False)
        db.commit()
        print(f"Mot de passe de « {user.username} » réinitialisé, compte déverrouillé.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
