from dataclasses import dataclass
import json
import sqlite3

from errors import EvidenceError
from storage import ArchiveStore
from volume.basis import Basis, Stripes, validate_basis
from volume.catalog import VolumeRecord
from volume.slots import Slots, read_slots


@dataclass(frozen=True, slots=True)
class VolumeEvidence:
    volume: VolumeRecord
    slots: Slots
    basis: Basis

    @property
    def generations(self) -> tuple[int, int, int]:
        return tuple(slot.generation for slot in self.slots)

    @property
    def payloads(self) -> Stripes:
        return tuple(slot.payload for slot in self.slots)

    @property
    def checksums(self) -> tuple[str, str, str]:
        return tuple(slot.checksum for slot in self.slots)


def published_layout(db: sqlite3.Connection, volume: VolumeRecord):
    receipt = db.execute(
        '''SELECT target, generations FROM recode_receipts WHERE volume_id = ?
           ORDER BY rowid DESC LIMIT 1''',
        (volume.volume_id,),
    ).fetchone()
    if receipt is None:
        return volume.initial_basis, volume.initial_generations
    try:
        basis = validate_basis(json.loads(receipt['target']))
        generations = tuple(json.loads(receipt['generations']))
        if len(generations) != 3 or any(type(value) is not int or value < 0 for value in generations):
            raise ValueError('invalid published generations')
    except (ValueError, TypeError) as exc:
        raise EvidenceError(f'invalid published layout for {volume.volume_id}') from exc
    return basis, generations


def _read_published(db: sqlite3.Connection, volume: VolumeRecord, slots: Slots) -> VolumeEvidence:
    basis, generations = published_layout(db, volume)
    evidence = VolumeEvidence(volume, slots, basis)
    if any(len(slot.payload) != volume.stripe_length for slot in slots):
        raise EvidenceError(f'wrong stripe length for {volume.volume_id}')
    if evidence.generations != generations:
        pending = db.execute(
            "SELECT 1 FROM recode_requests WHERE volume_id = ? AND status = 'pending'",
            (volume.volume_id,),
        ).fetchone()
        if pending is None or any(actual < published for actual, published in zip(evidence.generations, generations)):
            raise EvidenceError(f'medium generations do not match the publication for {volume.volume_id}')
    return evidence


def collect_volume_evidence(
    store: ArchiveStore, volume: VolumeRecord, *, db: sqlite3.Connection | None = None,
) -> VolumeEvidence:
    slots = read_slots(store, volume.volume_id, volume.medium_id)
    if db is not None:
        return _read_published(db, volume, slots)
    with store.catalog() as catalog:
        return _read_published(catalog, volume, slots)
