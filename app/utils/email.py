from __future__ import annotations

import re

_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned_value = value.strip().lower()
    if not cleaned_value:
        return None
    if not _EMAIL_REGEX.match(cleaned_value):
        return None
    return cleaned_value
