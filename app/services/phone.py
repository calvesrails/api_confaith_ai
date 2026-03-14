from ..utils.strings import only_digits


def normalize_phone(value: str) -> str | None:
    phone_digits = only_digits(value)
    if not phone_digits:
        return None

    national_number = _extract_national_number(phone_digits)
    if len(national_number) not in {10, 11}:
        return None

    ddd = national_number[:2]
    local_number = national_number[2:]
    if not ddd.isdigit() or not 11 <= int(ddd) <= 99:
        return None

    if classify_phone(national_number) is None:
        return None

    return f"55{ddd}{local_number}"


def classify_phone(value: str) -> str | None:
    national_number = _extract_national_number(only_digits(value))
    if len(national_number) < 10:
        return None

    local_number = national_number[2:]
    if len(local_number) == 9 and local_number.startswith("9"):
        return "mobile"
    if len(local_number) == 8 and local_number[:1] in {"2", "3", "4", "5"}:
        return "landline"
    return None


def _extract_national_number(phone_digits: str) -> str:
    if phone_digits.startswith("55") and len(phone_digits) in {12, 13}:
        return phone_digits[2:]
    return phone_digits
