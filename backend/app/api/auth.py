"""Authentification et gestion des utilisateurs / rôles."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import Principal, client_info, get_principal, require
from app.core.security import Perm, check_password_policy, create_access_token, hash_password, verify_password
from app.models import Role, User
from app.schemas import PasswordChange, RoleOut, Token, UserCreate, UserOut, UserUpdate
from app.services import audit
from app.services.audit import Actor

router = APIRouter(prefix="/api", tags=["Authentification & utilisateurs"])


@router.post("/auth/login", response_model=Token, summary="Connexion (retourne un jeton JWT)")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    s = get_settings()
    ip, ua = client_info(request)
    # identifiant insensible à la casse : « Admin » = « admin »
    user = db.execute(select(User).where(func.lower(User.username) == form.username.strip().lower())).scalar()
    now = datetime.now(timezone.utc)
    if user and user.locked_until:
        locked = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
        if locked > now:
            audit.log(db, Actor(user.id, user.username, ip, ua), "LOGIN_LOCKED", "user", str(user.id))
            raise HTTPException(status.HTTP_423_LOCKED, "Compte temporairement verrouillé (trop d'échecs)")
    if not user or not user.is_active or not verify_password(form.password, user.hashed_password):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= s.max_failed_logins:
                user.locked_until = now + timedelta(minutes=s.lockout_minutes)
                user.failed_logins = 0
            db.commit()
        audit.log(db, Actor(user.id if user else None, form.username[:80], ip, ua), "LOGIN_FAILED", "user",
                  str(user.id) if user else None)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants invalides")
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    token, expires = create_access_token(user.id, user.username, user.role.name)
    audit.log(db, Actor(user.id, user.username, ip, ua), "LOGIN", "user", str(user.id))
    return Token(access_token=token, expires_in=expires, role=user.role.name, permissions=user.role.permissions)


@router.get("/auth/me", summary="Profil de l'utilisateur connecté")
def me(p: Principal = Depends(get_principal)):
    return {"name": p.name, "role": p.role, "permissions": sorted(p.permissions),
            "user": UserOut.model_validate(p.user).model_dump() if p.user else None}


@router.post("/auth/password", status_code=204, summary="Changer son propre mot de passe")
def change_password(data: PasswordChange, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    if not p.user:
        raise HTTPException(400, "Réservé aux comptes utilisateurs (pas aux clés d'API)")
    user = db.get(User, p.user.id)
    if not verify_password(data.current_password, user.hashed_password):
        audit.log(db, p.actor, "PASSWORD_CHANGE_FAILED", "user", str(user.id))
        raise HTTPException(422, "Mot de passe actuel incorrect")
    if data.new_password == data.current_password:
        raise HTTPException(422, "Le nouveau mot de passe doit être différent de l'actuel")
    if err := check_password_policy(data.new_password):
        raise HTTPException(422, err)
    user.hashed_password = hash_password(data.new_password)
    audit.log(db, p.actor, "PASSWORD_CHANGE", "user", str(user.id), commit=False)
    db.commit()


@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: Session = Depends(get_db), _: Principal = Depends(get_principal)):
    return db.execute(select(Role).order_by(Role.id)).scalars().all()


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: Principal = Depends(require(Perm.USER_MANAGE))):
    return db.execute(select(User).order_by(User.username)).scalars().all()


def _role(db: Session, name: str) -> Role:
    role = db.execute(select(Role).where(Role.name == name)).scalar()
    if not role:
        raise HTTPException(422, f"Rôle inconnu : {name}")
    return role


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db), p: Principal = Depends(require(Perm.USER_MANAGE))):
    if err := check_password_policy(data.password):
        raise HTTPException(422, err)
    if db.execute(select(User).where((func.lower(User.username) == data.username.lower())
                                     | (func.lower(User.email) == data.email.lower()))).first():
        raise HTTPException(409, "Nom d'utilisateur ou e-mail déjà utilisé")
    user = User(username=data.username.lower(), email=data.email.lower(), full_name=data.full_name,
                hashed_password=hash_password(data.password), role_id=_role(db, data.role).id)
    db.add(user)
    db.flush()
    audit.log(db, p.actor, "USER_CREATE", "user", str(user.id), {"username": user.username, "role": data.role})
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db),
                p: Principal = Depends(require(Perm.USER_MANAGE))):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    is_self = p.user_id == user.id
    removes_admin = (data.is_active is False) or (data.role is not None and data.role != "admin")
    if is_self and removes_admin:
        raise HTTPException(409, "Vous ne pouvez pas désactiver votre propre compte ni retirer votre rôle administrateur")
    if removes_admin and user.role.name == "admin" and user.is_active:
        admins = db.execute(select(func.count(User.id)).join(Role).where(
            Role.name == "admin", User.is_active.is_(True))).scalar_one()
        if admins <= 1:
            raise HTTPException(409, "Il doit rester au moins un administrateur actif")
    changes = {}
    if data.full_name is not None:
        user.full_name = data.full_name
        changes["full_name"] = data.full_name
    if data.role is not None:
        user.role_id = _role(db, data.role).id
        changes["role"] = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
        changes["is_active"] = data.is_active
    if data.password:
        if err := check_password_policy(data.password):
            raise HTTPException(422, err)
        user.hashed_password = hash_password(data.password)
        changes["password"] = "modifié"
    if data.is_active or data.password:  # réactivation ou nouveau mot de passe : déverrouille le compte
        if user.locked_until or user.failed_logins:
            changes["unlocked"] = True
        user.locked_until = None
        user.failed_logins = 0
    audit.log(db, p.actor, "USER_UPDATE", "user", str(user.id), changes, commit=False)
    db.commit()
    db.refresh(user)
    return user
