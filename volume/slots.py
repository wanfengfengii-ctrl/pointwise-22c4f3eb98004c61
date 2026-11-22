from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from errors import ConflictError, EvidenceError, InvalidInput, require_text
from storage import ArchiveStore
from volume.basis import Stripes
from volume.integrity import slot_checksum, verify_slot_integrity


@dataclass(frozen=True, slots=True)
class SlotSnapshot:
    volume_id: str
    medium_id: str
    index: int
    generation: int
    payload: bytes
    checksum: str


@dataclass(frozen=True, slots=True)
class SlotWriteEvent:
    phase: Literal['before', 'after']
    previous_generation: int
    snapshot: SlotSnapshot


BoundaryHook = Callable[[SlotWriteEvent], None]
Slots = tuple[SlotSnapshot, SlotSnapshot, SlotSnapshot]


def _new_slot(volume_id: str, medium_id: str, index: int, generation: int, payload: bytes):
    return SlotSnapshot(
        volume_id, medium_id, index, generation, payload,
        slot_checksum(volume_id, medium_id, index, generation, payload),
    )


def initialize_slots(store: ArchiveStore, volume_id: str, medium_id: str, payloads: Stripes) -> None:
    require_text(volume_id, 'volume ID')
    require_text(medium_id, 'medium ID')
    if len(payloads) != 3 or any(not isinstance(payload, bytes) for payload in payloads):
        raise InvalidInput('the medium requires three byte payloads')
    if len({len(payload) for payload in payloads}) != 1:
        raise InvalidInput('slot payloads must have equal length')
    snapshots = tuple(_new_slot(volume_id, medium_id, i, 0, data) for i, data in enumerate(payloads))
    with store.media(write=True) as db:
        if db.execute('SELECT 1 FROM slots WHERE medium_id = ?', (medium_id,)).fetchone() is not None:
            raise ConflictError('medium is already initialized')
        db.executemany(
            '''INSERT INTO slots(medium_id, volume_id, slot_index, generation, payload, checksum)
               VALUES (?, ?, ?, ?, ?, ?)''',
            [
                (slot.medium_id, slot.volume_id, slot.index, slot.generation, slot.payload, slot.checksum)
                for slot in snapshots
            ],
        )


def discard_unpublished_slots(store: ArchiveStore, volume_id: str) -> None:
    """Release staging slots after the publisher has checked volume absence."""
    with store.media(write=True) as db:
        db.execute('DELETE FROM slots WHERE volume_id = ?', (volume_id,))


def _read_slot(volume_id: str, medium_id: str, index: int, row) -> SlotSnapshot:
    if row is None or row['volume_id'] != volume_id or row['slot_index'] != index:
        raise EvidenceError(f'missing or misbound slot {volume_id}/{index}')
    slot = SlotSnapshot(volume_id, medium_id, index, row['generation'], row['payload'], row['checksum'])
    verify_slot_integrity(volume_id, medium_id, index, slot.generation, slot.payload, slot.checksum)
    return slot


def read_slots(store: ArchiveStore, volume_id: str, medium_id: str) -> Slots:
    with store.media() as db:
        rows = db.execute(
            '''SELECT volume_id, slot_index, generation, payload, checksum FROM slots
               WHERE medium_id = ? ORDER BY slot_index''',
            (medium_id,),
        ).fetchall()
    if len(rows) != 3:
        raise EvidenceError(f'expected three slots for volume {volume_id}')
    return tuple(_read_slot(volume_id, medium_id, index, row) for index, row in enumerate(rows))


def compare_and_write_slot(
    store: ArchiveStore, volume_id: str, medium_id: str, index: int,
    expected_generation: int, payload: bytes, *, on_boundary: BoundaryHook | None = None,
) -> SlotSnapshot:
    if type(index) is not int or not 0 <= index < 3 or not isinstance(payload, bytes):
        raise InvalidInput('slot write requires a valid slot and byte payload')
    if type(expected_generation) is not int or not 0 <= expected_generation < 2**63 - 1:
        raise InvalidInput('slot write requires an incrementable generation')
    with store.media(write=True) as db:
        row = db.execute(
            '''SELECT volume_id, slot_index, generation, payload, checksum FROM slots
               WHERE medium_id = ? AND slot_index = ?''',
            (medium_id, index),
        ).fetchone()
        previous = _read_slot(volume_id, medium_id, index, row)
        if previous.generation != expected_generation:
            raise ConflictError(f'stale write to {volume_id}/{index} at generation {expected_generation}')
        if len(previous.payload) != len(payload):
            raise InvalidInput('slot write cannot change the stripe length')
        new_slot = _new_slot(volume_id, medium_id, index, expected_generation + 1, payload)
        if on_boundary is not None:
            on_boundary(SlotWriteEvent('before', expected_generation, new_slot))
        db.execute(
            '''UPDATE slots SET generation = ?, payload = ?, checksum = ?
               WHERE medium_id = ? AND slot_index = ? AND generation = ?''',
            (new_slot.generation, new_slot.payload, new_slot.checksum, medium_id, index, expected_generation),
        )
    if on_boundary is not None:
        on_boundary(SlotWriteEvent('after', expected_generation, new_slot))
    return new_slot
