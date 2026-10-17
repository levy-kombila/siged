"""Modèle de données GEDarchive (SQLAlchemy 2.0).

Séparation stricte : cette base ne contient que métadonnées, index et traces ;
les fichiers physiques sont dans l'Object Storage / système de fichiers chiffré.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------- Énumérations
class DocStatus:
    DRAFT = "DRAFT"                         # Brouillon
    PENDING = "PENDING_VALIDATION"          # En validation
    VALIDATED = "VALIDATED"                 # Validé / figé
    ARCHIVED = "ARCHIVED"                   # Archivage définitif (sort final)
    DESTROYED = "DESTROYED"                 # Éliminé (sort final)
    ALL = [DRAFT, PENDING, VALIDATED, ARCHIVED, DESTROYED]


class FinalDisposition:
    DESTROY = "DESTROY"
    ARCHIVE = "ARCHIVE"
    ALL = [DESTROY, ARCHIVE]


class ConversionStatus:
    PENDING = "PENDING"
    DONE = "DONE"
    PARTIAL = "PARTIAL"   # texte extrait mais pas de PDF/A (outil indisponible)
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


# ---------------------------------------------------------------- RBAC
class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    permissions: Mapped[list] = mapped_column(JSON, default=list)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    hashed_password: Mapped[str] = mapped_column(String(255))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    role: Mapped[Role] = relationship(lazy="joined")


class ApiKey(Base):
    """Clé d'API pour les applications tierces (ERP, SIRH, messagerie...)."""
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    key_prefix: Mapped[str] = mapped_column(String(12), index=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    role: Mapped[Role] = relationship(lazy="joined")


# ---------------------------------------------------------------- Plan de classement
class ClassificationNode(Base):
    __tablename__ = "classification_nodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)        # ex : RH.02.01
    label: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("classification_nodes.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    default_dua_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_final_disposition: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Règles de classement automatique
    rule_doc_types: Mapped[list] = mapped_column(JSON, default=list)
    rule_keywords: Mapped[list] = mapped_column(JSON, default=list)

    children: Mapped[list["ClassificationNode"]] = relationship(back_populates="parent")
    parent: Mapped["ClassificationNode | None"] = relationship(back_populates="children", remote_side=[id])


# ---------------------------------------------------------------- Rayonnage (archives physiques)
class ShelfKind:
    """Niveaux de localisation physique, du plus large au plus fin."""
    SITE = "SITE"            # Site / bâtiment
    SALLE = "SALLE"          # Salle / magasin d'archives
    RAYONNAGE = "RAYONNAGE"  # Rayonnage (épi, armoire)
    TRAVEE = "TRAVEE"        # Travée
    TABLETTE = "TABLETTE"    # Tablette (étagère)
    BOITE = "BOITE"          # Boîte / carton d'archives
    ALL = [SITE, SALLE, RAYONNAGE, TRAVEE, TABLETTE, BOITE]


class ShelfLocation(Base):
    __tablename__ = "shelf_locations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)       # ex : MAG1-R03-T2-B015
    label: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(20), default=ShelfKind.BOITE)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("shelf_locations.id"), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)  # nb max de documents
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    children: Mapped[list["ShelfLocation"]] = relationship(back_populates="parent")
    parent: Mapped["ShelfLocation | None"] = relationship(back_populates="children", remote_side=[id])

    @property
    def path(self) -> str:
        """Chemin lisible : « Magasin 1 › Rayonnage R03 › Boîte 15 »."""
        parts, node, seen = [], self, set()
        while node is not None and node.id not in seen:
            seen.add(node.id)
            parts.append(node.label)
            node = node.parent
        return " › ".join(reversed(parts))


# ---------------------------------------------------------------- Documents
def compute_retention_until(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 février
        return d.replace(year=d.year + years, day=28)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    reference: Mapped[str] = mapped_column(String(40), unique=True)   # cote lisible : DOC-2026-000123
    # Fiche de métadonnées obligatoire
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str] = mapped_column(String(255))
    document_date: Mapped[date] = mapped_column(Date)
    doc_type: Mapped[str] = mapped_column(String(100), index=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    dua_years: Mapped[int] = mapped_column(Integer)
    final_disposition: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(Text, default="")
    # Classement / cycle de vie
    classification_id: Mapped[int | None] = mapped_column(ForeignKey("classification_nodes.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=DocStatus.DRAFT, index=True)
    retention_until: Mapped[date] = mapped_column(Date, index=True)  # document_date + DUA
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)  # gel (contentieux)
    # Date à laquelle le document devient obsolète (fin de validité : contrat, attestation, agrément...)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    # Exemplaire papier : emplacement dans le rayonnage
    shelf_location_id: Mapped[int | None] = mapped_column(ForeignKey("shelf_locations.id"), nullable=True, index=True)
    physical_ref: Mapped[str] = mapped_column(String(100), default="")
    source: Mapped[str] = mapped_column(String(30), default="upload")  # upload|batch|api|hotfolder|email
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    classification: Mapped[ClassificationNode | None] = relationship(lazy="joined")
    creator: Mapped[User | None] = relationship(lazy="joined")
    shelf_location: Mapped[ShelfLocation | None] = relationship(lazy="joined")
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", order_by="DocumentVersion.created_at", cascade="all, delete-orphan")
    extra_metadata: Mapped[list["DocumentMetadata"]] = relationship(cascade="all, delete-orphan")

    __table_args__ = (Index("ix_documents_date", "document_date"),)

    @property
    def extra(self) -> dict[str, str]:
        return {m.meta_key: m.meta_value for m in self.extra_metadata}

    @property
    def current_version(self) -> "DocumentVersion | None":
        return next((v for v in self.versions if v.is_current), None)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    major: Mapped[int] = mapped_column(Integer)
    minor: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False)  # figé après validation
    comment: Mapped[str] = mapped_column(Text, default="")
    # Fichier original
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(150))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Représentation pérenne (PDF/A)
    archival_format: Mapped[str | None] = mapped_column(String(30), nullable=True)
    archival_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    archival_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archival_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    conversion_status: Mapped[str] = mapped_column(String(20), default=ConversionStatus.PENDING)
    conversion_log: Mapped[str] = mapped_column(Text, default="")
    ocr_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("document_id", "major", "minor", name="uq_version_number"),)

    @property
    def label(self) -> str:
        return f"{self.major}.{self.minor}"


class DocumentMetadata(Base):
    """Métadonnées dynamiques complémentaires (ex : n° facture, matricule agent)."""
    __tablename__ = "document_metadata"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    meta_key: Mapped[str] = mapped_column(String(100), index=True)
    meta_value: Mapped[str] = mapped_column(Text)


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(100), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- Traçabilité
class AuditLog(Base):
    """Journal d'audit chaîné (chaque entrée scelle la précédente par SHA-256).
    En PostgreSQL, un trigger interdit UPDATE / DELETE / TRUNCATE."""
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    action: Mapped[str] = mapped_column(String(50), index=True)
    object_type: Mapped[str] = mapped_column(String(50), default="")
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ip_address: Mapped[str] = mapped_column(String(45), default="")
    user_agent: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True)


class IntegrityCheck(Base):
    __tablename__ = "integrity_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    files_checked: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[list] = mapped_column(JSON, default=list)


class Webhook(Base):
    __tablename__ = "webhooks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(500))
    events: Mapped[list] = mapped_column(JSON, default=list)  # ["document.validated", "*"]
    secret: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Sequence(Base):
    """Compteur pour les cotes lisibles (DOC-AAAA-NNNNNN)."""
    __tablename__ = "sequences"
    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------- Notifications
class NotificationKind:
    VALIDITY = "VALIDITY"    # fin de validité : le document devient obsolète
    RETENTION = "RETENTION"  # DUA échue : sort final à appliquer
    ALL = [VALIDITY, RETENTION]


class Notification(Base):
    """Alerte adressée à un utilisateur (une seule par document, type et palier)."""
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str] = mapped_column(String(10))       # J-90, J-30, J-7, ECHU
    due_date: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "document_id", "kind", "stage", name="uq_notification_stage"),)
