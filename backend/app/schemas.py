"""Schémas d'entrée / sortie de l'API (Pydantic v2)."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import FinalDisposition, ShelfKind


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------- Auth / utilisateurs
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    permissions: list[str]


class RoleOut(ORM):
    id: int
    name: str
    description: str
    permissions: list[str]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: EmailStr
    full_name: str = ""
    password: str
    role: str = "lecteur"


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


class UserOut(ORM):
    id: int
    username: str
    email: str
    full_name: str
    is_active: bool
    role: RoleOut
    created_at: datetime
    locked_until: datetime | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


# ------------------------------------------------------------- Plan de classement
class ClassificationIn(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=255)
    parent_id: int | None = None
    description: str = ""
    default_dua_years: int | None = Field(default=None, ge=0, le=200)
    default_final_disposition: str | None = None
    rule_doc_types: list[str] = []
    rule_keywords: list[str] = []

    @field_validator("default_final_disposition")
    @classmethod
    def _disp(cls, v):
        if v is not None and v not in FinalDisposition.ALL:
            raise ValueError("Sort final : DESTROY ou ARCHIVE")
        return v


class ClassificationOut(ORM):
    id: int
    code: str
    label: str
    parent_id: int | None
    default_dua_years: int | None
    default_final_disposition: str | None
    rule_doc_types: list[str]
    rule_keywords: list[str]


# ------------------------------------------------------------- Rayonnage
class ShelfLocationIn(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=255)
    kind: str = ShelfKind.BOITE
    parent_id: int | None = None
    capacity: int | None = Field(default=None, ge=1, le=100000)
    description: str = ""

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in ShelfKind.ALL:
            raise ValueError("Niveau : " + ", ".join(ShelfKind.ALL))
        return v


class ShelfLocationRef(ORM):
    id: int
    code: str
    label: str
    kind: str
    path: str


class ShelfLocationOut(ShelfLocationRef):
    parent_id: int | None
    capacity: int | None
    description: str


class DocumentLocationIn(BaseModel):
    shelf_location_id: int | None = None
    physical_ref: str = Field(default="", max_length=100)


# ------------------------------------------------------------- Documents
class DocumentMetaIn(BaseModel):
    """Fiche de métadonnées. Champs obligatoires : titre, auteur, date, type, mots-clés, DUA
    (la DUA et le sort final peuvent être hérités de la rubrique du plan de classement)."""
    title: str = Field(min_length=1, max_length=255)
    author: str = Field(min_length=1, max_length=255)
    document_date: date
    doc_type: str = Field(min_length=1, max_length=100)
    keywords: list[str] = Field(min_length=1)
    dua_years: int | None = Field(default=None, ge=0, le=200)
    final_disposition: str | None = None
    description: str = ""
    valid_until: date | None = None
    classification_id: int | None = None
    classification_code: str | None = None
    extra_metadata: dict[str, str] = {}

    @field_validator("keywords")
    @classmethod
    def _kw(cls, v):
        v = [k.strip() for k in v if k and k.strip()]
        if not v:
            raise ValueError("Au moins un mot-clé est obligatoire")
        return v

    @field_validator("final_disposition")
    @classmethod
    def _disp(cls, v):
        if v is not None and v not in FinalDisposition.ALL:
            raise ValueError("Sort final : DESTROY ou ARCHIVE")
        return v


class DocumentMetaUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    author: str | None = None
    document_date: date | None = None
    doc_type: str | None = None
    keywords: list[str] | None = None
    dua_years: int | None = Field(default=None, ge=0, le=200)
    final_disposition: str | None = None
    description: str | None = None
    valid_until: date | None = None
    classification_id: int | None = None
    extra_metadata: dict[str, str] | None = None


class VersionOut(ORM):
    id: str
    label: str
    major: int
    minor: int
    is_current: bool
    is_frozen: bool
    comment: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    archival_format: str | None
    archival_sha256: str | None
    conversion_status: str
    ocr_applied: bool
    created_at: datetime


class DocumentOut(ORM):
    id: str
    reference: str
    title: str
    author: str
    document_date: date
    doc_type: str
    keywords: list[str]
    dua_years: int
    final_disposition: str
    retention_until: date
    valid_until: date | None = None
    description: str
    status: str
    legal_hold: bool
    shelf_location: ShelfLocationRef | None = None
    physical_ref: str = ""
    source: str
    classification: ClassificationOut | None
    created_at: datetime
    updated_at: datetime
    validated_at: datetime | None
    disposed_at: datetime | None
    current_version: VersionOut | None
    extra: dict[str, str] = {}


class DocumentDetail(DocumentOut):
    versions: list[VersionOut]


class SearchHit(DocumentOut):
    score: float | None = None
    snippet: str | None = None


class SearchResult(BaseModel):
    total: int
    page: int
    size: int
    took_ms: float
    items: list[SearchHit]


class BatchResult(BaseModel):
    created: list[DocumentOut]
    errors: list[dict]


class WorkflowAction(BaseModel):
    comment: str = ""


class WorkflowEventOut(ORM):
    from_status: str
    to_status: str
    actor_name: str
    comment: str
    created_at: datetime


class LegalHoldIn(BaseModel):
    legal_hold: bool
    reason: str = Field(min_length=3)


# ------------------------------------------------------------- Audit / admin
class AuditOut(ORM):
    id: int
    created_at: datetime
    user_id: int | None
    actor: str
    action: str
    object_type: str
    object_id: str | None
    ip_address: str
    details: dict
    entry_hash: str


class RetentionRunIn(BaseModel):
    document_ids: list[str] | None = None
    dry_run: bool = True


# ------------------------------------------------------------- Intégrations
class ApiKeyIn(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    role: str = "contributeur"


class ApiKeyOut(ORM):
    id: int
    name: str
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    role: RoleOut


class ApiKeyCreated(ApiKeyOut):
    api_key: str  # affichée une seule fois


class WebhookIn(BaseModel):
    name: str
    url: str = Field(pattern=r"^https?://")
    events: list[str] = ["*"]


class WebhookOut(ORM):
    id: int
    name: str
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime


class WebhookCreated(WebhookOut):
    secret: str


# ------------------------------------------------------------- Notifications
class NotificationOut(ORM):
    id: int
    document_id: str | None
    kind: str
    stage: str
    due_date: date
    title: str
    message: str
    created_at: datetime
    read_at: datetime | None


class NotificationList(BaseModel):
    unread: int
    items: list[NotificationOut]


class ObsolescenceItem(BaseModel):
    kind: str            # VALIDITY | RETENTION
    due_date: date
    days_left: int       # négatif = déjà échu
    document: "DocumentOut"

