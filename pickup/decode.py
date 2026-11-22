from volume.basis import Basis, Stripes, encode_stripes, invert_basis


def decode_original(basis: Basis, encoded: Stripes) -> Stripes:
    return encode_stripes(invert_basis(basis), encoded)
