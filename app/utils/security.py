from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets


@dataclass(frozen=True, slots=True)
class GeneratedApiToken:
    raw_token: str
    token_prefix: str
    token_hash: str


def hash_api_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def verify_api_token(raw_token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_api_token(raw_token), token_hash)


def generate_api_token(prefix: str = "tkn_live") -> GeneratedApiToken:
    random_part = secrets.token_urlsafe(32)
    raw_token = f"{prefix}_{random_part}"
    return GeneratedApiToken(
        raw_token=raw_token,
        token_prefix=raw_token[:16],
        token_hash=hash_api_token(raw_token),
    )


def mask_secret(value: str | None, *, keep_start: int = 4, keep_end: int = 4) -> str | None:
    if not value:
        return None
    if len(value) <= keep_start + keep_end:
        return "*" * len(value)
    return f"{value[:keep_start]}{'*' * (len(value) - keep_start - keep_end)}{value[-keep_end:]}"
