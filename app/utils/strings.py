def only_digits(value: str | None) -> str:
    if value is None:
        return ""
    return "".join(character for character in value if character.isdigit())
