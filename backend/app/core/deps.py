"""Dépendances FastAPI : identification (JWT ou clé d'API) et contrôle RBAC."""
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token, hash_api_key
from app.models import ApiKey, User
from app.services.audit import Actor

bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    """Utilisateur authentifié OU application cliente (clé d'API)."""
    name: str
    role: str
    permissions: set[str]
    user: User | None = None
    api_key: ApiKey | None = None
    ip: str = ""
    user_agent: str = ""

    @property
    def user_id(self) -> int | None:
        return self.user.id if self.user else None

    @property
    def actor(self) -> Actor:
        return Actor(self.user_id, self.name, self.ip, self.user_agent)

    def can(self, perm: str) -> bool:
        return perm in self.permissions


def client_info(request: Request) -> tuple[str, str]:
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
    return ip, request.headers.get("user-agent", "")


def get_principal(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                  db: Session = Depends(get_db)) -> Principal:
    ip, ua = client_info(request)
    raw_key = request.headers.get("x-api-key")
    if raw_key:
        key = db.execute(select(ApiKey).where(ApiKey.key_prefix == raw_key[:12],
                                              ApiKey.key_hash == hash_api_key(raw_key))).scalar()
        if not key or not key.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Clé d'API invalide")
        key.last_used_at = datetime.now(timezone.utc)
        db.commit()
        return Principal(name=f"api:{key.name}", role=key.role.name, permissions=set(key.role.permissions),
                         api_key=key, ip=ip, user_agent=ua)
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise",
                            headers={"WWW-Authenticate": "Bearer"})
    payload = decode_access_token(creds.credentials)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton invalide ou expiré",
                            headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Compte inactif")
    return Principal(name=user.username, role=user.role.name, permissions=set(user.role.permissions),
                     user=user, ip=ip, user_agent=ua)


def require(*perms: str):
    """Usage : principal = Depends(require(Perm.DOC_WRITE))"""
    def checker(p: Principal = Depends(get_principal)) -> Principal:
        missing = [x for x in perms if not p.can(x)]
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Permission manquante : {', '.join(missing)}")
        return p
    return checker
