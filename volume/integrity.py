from hashlib import sha256
from hmac import compare_digest

from errors import EvidenceError


def slot_checksum(volume_id: str, medium_id: str, index: int, generation: int, payload: bytes) -> str:
    digest = sha256(b'waveform-slot-v1\x00')
    for identifier in (volume_id, medium_id):
        encoded = identifier.encode('utf-8')
        digest.update(len(encoded).to_bytes(8, 'big'))
        digest.update(encoded)
    digest.update(index.to_bytes(1, 'big'))
    digest.update(generation.to_bytes(8, 'big'))
    digest.update(len(payload).to_bytes(8, 'big'))
    digest.update(payload)
    return digest.hexdigest()


def verify_slot_integrity(
    volume_id: str, medium_id: str, index: int, generation: int, payload: bytes, checksum: str
) -> None:
    if (
        type(index) is not int or not 0 <= index < 3
        or type(generation) is not int or not 0 <= generation < 2**63
        or not isinstance(payload, bytes)
        or not isinstance(checksum, str) or len(checksum) != 64 or not checksum.isascii()
    ):
        raise EvidenceError(f'invalid stored slot fields for {volume_id}/{index}')
    expected = slot_checksum(volume_id, medium_id, index, generation, payload)
    if not compare_digest(expected, checksum):
        raise EvidenceError(f'checksum mismatch for {volume_id}/{index} generation {generation}')
