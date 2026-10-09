"""Capture depuis la messagerie (IMAP) : chaque pièce jointe d'un e-mail non lu devient
un document (titre = objet du message, auteur = expéditeur, date = date du message).
Le message est ensuite marqué comme lu. Activé si SIGED_IMAP_HOST est renseigné."""
import email
import imaplib
import io
import logging
from datetime import date
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.schemas import DocumentMetaIn
from app.services import documents as svc
from app.services.audit import Actor

logger = logging.getLogger("siged.mail")
MAIL_ACTOR = Actor(None, "system:imap")


def _decode(value: str | None) -> str:
    return str(make_header(decode_header(value))) if value else ""


def extract_attachments(raw: bytes) -> tuple[dict, list[tuple[str, bytes, str]]]:
    msg = email.message_from_bytes(raw)
    subject = _decode(msg.get("Subject")) or "Courriel sans objet"
    name, addr = parseaddr(_decode(msg.get("From")))
    try:
        d = parsedate_to_datetime(msg.get("Date")).date()
    except Exception:  # noqa: BLE001
        d = date.today()
    atts = []
    for part in msg.walk():
        if part.get_content_disposition() == "attachment" and part.get_filename():
            atts.append((_decode(part.get_filename()), part.get_payload(decode=True) or b"", part.get_content_type()))
    return {"subject": subject, "author": name or addr or "inconnu", "date": d, "from": addr}, atts


def ingest_message(raw: bytes) -> list[str]:
    info, atts = extract_attachments(raw)
    refs = []
    for filename, content, ctype in atts:
        db = SessionLocal()
        try:
            meta = DocumentMetaIn(title=f"{info['subject']} - {filename}", author=info["author"],
                                  document_date=info["date"], doc_type="courrier",
                                  keywords=["courriel", "correspondance"],
                                  extra_metadata={"email_from": info["from"], "email_subject": info["subject"]})
            received = svc.receive_stream(io.BytesIO(content), filename, ctype)
            try:
                doc, version = svc.create_document(db, MAIL_ACTOR, received, meta, source="email")
            finally:
                received.cleanup()
            svc.process_version(version.id)
            refs.append(doc.reference)
        except svc.BusinessError as exc:
            db.rollback()
            logger.warning("Pièce jointe %s ignorée : %s", filename, exc.message)
        finally:
            db.close()
    return refs


def poll() -> int:
    s = get_settings()
    if not s.imap_host:
        return 0
    count = 0
    with imaplib.IMAP4_SSL(s.imap_host) as imap:
        imap.login(s.imap_user, s.imap_password)
        imap.select(s.imap_folder)
        _, data = imap.search(None, "UNSEEN")
        for num in data[0].split():
            _, msg_data = imap.fetch(num, "(RFC822)")
            count += len(ingest_message(msg_data[0][1]))
            imap.store(num, "+FLAGS", "\\Seen")
    return count
