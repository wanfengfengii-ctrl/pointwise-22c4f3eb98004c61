import sqlite3

from errors import EvidenceError
from pickup.evidence import VolumeEvidence, published_layout
from recode.progress import acknowledged_writes
from volume.basis import validate_basis


def acknowledged_view(db: sqlite3.Connection, view: VolumeEvidence, request_id: str) -> VolumeEvidence:
    basis, published_generations = published_layout(db, view.volume)
    rows = list(basis)
    generations = list(published_generations)
    for write in acknowledged_writes(db, request_id):
        index = write.slot_index
        if (write.volume_id != view.volume.volume_id or generations[index] != write.old_generation
                or rows[index] != write.old_row):
            raise EvidenceError(f'inconsistent acknowledged writes for {request_id}')
        generations[index] = write.new_generation
        rows[index] = write.new_row
    if tuple(generations) != view.generations:
        raise EvidenceError(f'medium has unacknowledged changes for {request_id}')
    try:
        current = validate_basis(rows)
    except ValueError as exc:
        raise EvidenceError(f'cannot resume the layout for {request_id}') from exc
    return VolumeEvidence(view.volume, view.slots, current)
