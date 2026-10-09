"""Authentification : mots de passe (bcrypt), jetons JWT, clés d'API, permissions RBAC."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


# ------------------------------------------------------------------ Permissions
class Perm:
    DOC_READ = "document:read"
    DOC_WRITE = "document:write"
    DOC_VALIDATE = "document:validate"
    DOC_DELETE = "document:delete"
    CLASSIFICATION_MANAGE = "classification:manage"
    RETENTION_MANAGE = "retention:manage"
    AUDIT_READ = "audit:read"
    USER_MANAGE = "user:manage"
    INTEGRATION_MANAGE = "integration:manage"
    ADMIN_JOBS = "admin:jobs"

    ALL = [DOC_READ, DOC_WRITE, DOC_VALIDATE, DOC_DELETE, CLASSIFICATION_MANAGE,
           RETENTION_MANAGE, AUDIT_READ, USER_MANAGE, INTEGRATION_MANAGE, ADMIN_JOBS]


DEFAULT_ROLES: dict[str, tuple[str, list[str]]] = {
    "admin": ("Administrateur : tous les droits", Perm.ALL),
    "archiviste": ("Gestion du plan de classement, de la DUA et de l'audit",
                   [Perm.DOC_READ, Perm.DOC_WRITE, Perm.CLASSIFICATION_MANAGE,
                    Perm.RETENTION_MANAGE, Perm.AUDIT_READ, Perm.ADMIN_JOBS]),
    "validateur": ("Approuve ou rejette les documents soumis", [Perm.DOC_READ, Perm.DOC_VALIDATE]),
    "contributeur": ("Dépose et met à jour des documents", [Perm.DOC_READ, Perm.DOC_WRITE]),
    "lecteur": ("Consultation seule", [Perm.DOC_READ]),
}


# ------------------------------------------------------------------ Mots de passe
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def check_password_policy(password: str) -> str | None:
    s = get_settings()
    if len(password) < s.password_min_length:
        return f"Le mot de passe doit contenir au moins {s.password_min_length} caractères."
    classes = [any(c.islower() for c in password), any(c.isupper() for c in password),
               any(c.isdigit() for c in password), any(not c.isalnum() for c in password)]
    if sum(classes) < 3:
        return "Le mot de passe doit combiner au moins 3 types : minuscules, majuscules, chiffres, symboles."
    return None


# ------------------------------------------------------------------ JWT
def create_access_token(user_id: int, username: str, role: str) -> tuple[str, int]:
    s = get_settings()
    expires = timedelta(minutes=s.access_token_minutes)
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "username": username, "role": role,
               "iat": now, "exp": now + expires, "jti": secrets.token_hex(8)}
    return jwt.encode(payload, s.secret_key, algorithm=ALGORITHM), int(expires.total_seconds())


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


# ------------------------------------------------------------------ Clés d'API
def generate_api_key() -> tuple[str, str, str]:
    """Retourne (clé en clair à montrer une seule fois, préfixe, empreinte SHA-256)."""
    raw = "sged_" + secrets.token_urlsafe(32)
    return raw, raw[:12], hashlib.sha256(raw.encode()).hexdigest()


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
