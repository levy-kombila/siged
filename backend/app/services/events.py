"""Interopérabilité sortante : webhooks signés (ERP, SIRH...) et notifications e-mail.

Chaque webhook reçoit un POST JSON avec l'en-tête
    X-SIGED-Signature: sha256=<HMAC-SHA256(secret, corps)>
pour que le système destinataire puisse vérifier l'authenticité du message.
"""
import hashlib
import hmac
import json
import logging
import smtplib
import threading
from datetime import datetime, timezone
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Webhook

logger = logging.getLogger("siged.events")

EVENTS = ["document.created", "document.version_added", "document.submitted", "document.validated",
          "document.rejected", "document.archived", "document.destroyed", "integrity.failure"]

# Hook de test : si défini, reçoit (url, headers, body) au lieu d'un envoi HTTP réel
_sender_override = None


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(url: str, headers: dict, body: bytes) -> None:
    if _sender_override:
        _sender_override(url, headers, body)
        return
    for attempt in range(3):
        try:
            r = httpx.post(url, content=body, headers=headers, timeout=5)
            if r.status_code < 500:
                return
        except httpx.HTTPError as exc:
            logger.warning("Webhook %s tentative %s : %s", url, attempt + 1, exc)


def emit(db: Session, event: str, payload: dict, synchronous: bool = False) -> int:
    hooks = db.execute(select(Webhook).where(Webhook.is_active.is_(True))).scalars().all()
    body = json.dumps({"event": event, "sent_at": datetime.now(timezone.utc).isoformat(),
                       "data": payload}, default=str, ensure_ascii=False).encode()
    sent = 0
    for h in hooks:
        if "*" not in h.events and event not in h.events:
            continue
        headers = {"Content-Type": "application/json", "X-SIGED-Event": event,
                   "X-SIGED-Signature": sign(h.secret, body)}
        if synchronous or _sender_override:
            _post(h.url, headers, body)
        else:
            threading.Thread(target=_post, args=(h.url, headers, body), daemon=True).start()
        sent += 1
    return sent


def send_email(to: list[str], subject: str, text: str) -> bool:
    s = get_settings()
    if not s.smtp_host or not to:
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, ", ".join(to), subject
    msg.set_content(text)

    def _send():
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Envoi e-mail impossible : %s", exc)

    threading.Thread(target=_send, daemon=True).start()
    return True
