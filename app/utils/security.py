from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

from ..core.config import get_settings

_SECRET_PREFIX = 'enc:v1:'


@dataclass(frozen=True, slots=True)
class GeneratedApiToken:
    raw_token: str
    token_prefix: str
    token_hash: str


def hash_api_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


def verify_api_token(raw_token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_api_token(raw_token), token_hash)


def generate_api_token(prefix: str = 'tkn_live') -> GeneratedApiToken:
    random_part = secrets.token_urlsafe(32)
    raw_token = f'{prefix}_{random_part}'
    return GeneratedApiToken(
        raw_token=raw_token,
        token_prefix=raw_token[:16],
        token_hash=hash_api_token(raw_token),
    )


def mask_secret(value: str | None, *, keep_start: int = 4, keep_end: int = 4) -> str | None:
    if not value:
        return None
    if len(value) <= keep_start + keep_end:
        return '*' * len(value)
    return f"{value[:keep_start]}{'*' * (len(value) - keep_start - keep_end)}{value[-keep_end:]}"


def encrypt_provider_secret(value: str | None) -> str | None:
    if not value:
        return value
    if value.startswith(_SECRET_PREFIX):
        return value
    encrypted = _get_secret_cipher().encrypt(value.encode('utf-8')).decode('utf-8')
    return f'{_SECRET_PREFIX}{encrypted}'


def decrypt_provider_secret(value: str | None) -> str | None:
    if not value:
        return value
    if not value.startswith(_SECRET_PREFIX):
        return value
    encrypted = value[len(_SECRET_PREFIX) :]
    try:
        return _get_secret_cipher().decrypt(encrypted.encode('utf-8')).decode('utf-8')
    except InvalidToken as error:
        raise ValueError(
            'Nao foi possivel descriptografar um segredo salvo. Verifique SECRET_ENCRYPTION_KEY.'
        ) from error


def _get_secret_cipher() -> Fernet:
    settings = get_settings()
    key_material = (
        settings.secret_encryption_key
        or settings.platform_admin_api_key
        or f'{settings.app_name}:{settings.app_env}:local-dev-only'
    )
    digest = hashlib.sha256(key_material.encode('utf-8')).digest()
    derived_key = base64.urlsafe_b64encode(digest)
    return Fernet(derived_key)
