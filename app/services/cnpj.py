from ..utils.strings import only_digits


def normalize_cnpj(value: str) -> str:
    return only_digits(value)


def is_valid_cnpj(value: str) -> bool:
    cnpj = normalize_cnpj(value)
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False

    first_digit = _calculate_digit(cnpj[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    second_digit = _calculate_digit(
        cnpj[:12] + str(first_digit),
        [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
    )
    return cnpj[-2:] == f"{first_digit}{second_digit}"


def _calculate_digit(base: str, factors: list[int]) -> int:
    total = sum(int(number) * factor for number, factor in zip(base, factors))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder
