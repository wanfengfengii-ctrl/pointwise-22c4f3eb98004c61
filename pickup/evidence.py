from dataclasses import dataclass
import sqlite3

from errors import EvidenceError
from recode.progress import resolve_medium_layout
from storage import ArchiveStore
from volume.basis import Basis, Stripes
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


def _read_medium(db: sqlite3.Connection, volume: VolumeRecord, slots: Slots) -> VolumeEvidence:
    basis, generations = resolve_medium_layout(db, volume, slots)
    if any(len(slot.payload) != volume.stripe_length for slot in slots):
        raise EvidenceError(f'wrong stripe length for {volume.volume_id}')
    if generations != tuple(slot.generation for slot in slots):
        raise EvidenceError(f'medium generations do not match the layout for {volume.volume_id}')
    return VolumeEvidence(volume, slots, basis)


def collect_volume_evidence(
    store: ArchiveStore, volume: VolumeRecord, *, db: sqlite3.Connection | None = None,
) -> VolumeEvidence:
    slots = read_slots(store, volume.volume_id, volume.medium_id)
    if db is not None:
        return _read_medium(db, volume, slots)
    with store.catalog() as catalog:
        return _read_medium(catalog, volume, slots)
