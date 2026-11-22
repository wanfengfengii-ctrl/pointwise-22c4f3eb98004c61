from errors import InvalidInput


Basis = tuple[int, int, int]
Stripes = tuple[bytes, bytes, bytes]


def _rows(basis) -> Basis:
    try:
        rows = tuple(basis)
    except TypeError as exc:
        raise InvalidInput('basis must contain three ordered row masks') from exc
    if len(rows) != 3 or any(type(row) is not int or not 1 <= row <= 7 for row in rows):
        raise InvalidInput('basis must contain three row masks in 1 through 7')
    return rows


def _inverse(rows: Basis) -> Basis:
    left = list(rows)
    right = [1, 2, 4]
    for index in range(3):
        bit = 1 << index
        pivot = next((i for i in range(index, 3) if left[i] & bit), None)
        if pivot is None:
            raise InvalidInput('basis is not invertible over GF(2)')
        left[index], left[pivot] = left[pivot], left[index]
        right[index], right[pivot] = right[pivot], right[index]
        for other in range(3):
            if other != index and left[other] & bit:
                left[other] ^= left[index]
                right[other] ^= right[index]
    return tuple(right)


def validate_basis(basis) -> Basis:
    rows = _rows(basis)
    _inverse(rows)
    return rows


def invert_basis(basis) -> Basis:
    return _inverse(_rows(basis))


def express_row(mask: int, inverse: Basis) -> int:
    """Express an original-channel mask in the basis whose inverse is given."""
    coefficients = 0
    for index, row in enumerate(inverse):
        if mask & (1 << index):
            coefficients ^= row
    return coefficients


def xor_stripes(*stripes: bytes) -> bytes:
    if not stripes or any(not isinstance(stripe, bytes) for stripe in stripes):
        raise InvalidInput('XOR requires one or more byte stripes')
    length = len(stripes[0])
    if any(len(stripe) != length for stripe in stripes):
        raise InvalidInput('XOR requires equal stripe lengths')
    if len(stripes) == 1:
        return stripes[0]
    result = bytearray(stripes[0])
    for stripe in stripes[1:]:
        for index, value in enumerate(stripe):
            result[index] ^= value
    return bytes(result)


def encode_row(mask: int, stripes: Stripes) -> bytes:
    return xor_stripes(*(stripe for index, stripe in enumerate(stripes) if mask & (1 << index)))


def encode_stripes(basis, stripes: Stripes) -> Stripes:
    rows = validate_basis(basis)
    if len(stripes) != 3 or any(not isinstance(stripe, bytes) for stripe in stripes):
        raise InvalidInput('encoding requires three byte stripes')
    if len({len(stripe) for stripe in stripes}) != 1:
        raise InvalidInput('encoding requires equal stripe lengths')
    return tuple(encode_row(row, stripes) for row in rows)
