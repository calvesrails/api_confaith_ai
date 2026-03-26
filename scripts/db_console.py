from __future__ import annotations

import code
import sys
from pathlib import Path

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.models import (
    ApiTokenModel,
    CallAttemptModel,
    EmailMessageModel,
    EmailSenderProfileModel,
    OpenAICredentialModel,
    PlatformAccountModel,
    TwilioCredentialModel,
    TwilioPhoneNumberModel,
    ValidationBatchModel,
    ValidationRecordModel,
    WhatsAppMessageModel,
)
from app.db.session import SessionLocal

session = SessionLocal()


def sql(query: str):
    return session.execute(text(query)).all()


def first(model):
    return session.query(model).first()


def all_rows(model, limit: int = 20):
    return session.query(model).limit(limit).all()


BANNER = """\
Database console carregado.

Objetos disponiveis:
- session
- sql("select * from validation_batches limit 5")
- first(Model)
- all_rows(Model, limit=20)

Models disponiveis:
- PlatformAccountModel
- ApiTokenModel
- TwilioCredentialModel
- TwilioPhoneNumberModel
- OpenAICredentialModel
- EmailSenderProfileModel
- ValidationBatchModel
- ValidationRecordModel
- CallAttemptModel
- EmailMessageModel
- WhatsAppMessageModel

Exemplos:
- session.query(PlatformAccountModel).all()
- session.query(ValidationBatchModel).order_by(ValidationBatchModel.id.desc()).limit(10).all()
- sql("select id, batch_id, batch_status from validation_batches order by id desc limit 10")
"""


try:
    code.interact(banner=BANNER, local=globals())
finally:
    session.close()
