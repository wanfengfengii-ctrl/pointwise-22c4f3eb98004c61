from dataclasses import dataclass
import sqlite3

from errors import EvidenceError
from volume.basis import Basis, validate_basis


@dataclass(frozen=True, slots=True)
class SlotWriteIntent:
    request_id: str
    volume_id: str
    slot_index: int
    old_generation: int
    old_row: int
    new_row: int
    confirmed: bool = False

    @property
    def new_generation(self) -> int:
        return self.old_generation + 1


def _intent_from_row(row: sqlite3.Row) -> SlotWriteIntent:
    return SlotWriteIntent(
        row['request_id'], row['volume_id'], row['slot_index'], row['old_generation'],
        row['old_row'], row['new_row'], bool(row['confirmed']),
    )


def record_intent(db: sqlite3.Connection, intent: SlotWriteIntent) -> None:
    db.execute(
        '''INSERT INTO slot_write_intents(request_id, volume_id, slot_index, old_generation,
                                          new_generation, old_row, new_row)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (
            intent.request_id, intent.volume_id, intent.slot_index, intent.old_generation,
            intent.new_generation, intent.old_row, intent.new_row,
        ),
    )


def record_pending_intent(db: sqlite3.Connection, intent: SlotWriteIntent) -> None:
    """Durably announce a slot write before the medium is touched.

    The directory and the medium commit separately, so a lost reply has to
    leave behind evidence of what may have been written.  An identical
    unresolved intent from the interrupted attempt is reused, not duplicated.
    """
    row = db.execute(
        '''SELECT request_id, volume_id, slot_index, old_generation, old_row, new_row, confirmed
           FROM slot_write_intents WHERE volume_id = ? AND confirmed = 0''',
        (intent.volume_id,),
    ).fetchone()
    if row is not None:
        existing = _intent_from_row(row)
        if (existing.request_id, existing.slot_index, existing.old_generation, existing.old_row,
                existing.new_row) != (intent.request_id, intent.slot_index, intent.old_generation,
                                      intent.old_row, intent.new_row):
            raise EvidenceError('an unconfirmed slot write disagrees with the recode plan')
        return
    record_intent(db, intent)


def find_pending_intent(db: sqlite3.Connection, request_id: str) -> SlotWriteIntent | None:
    row = db.execute(
        '''SELECT request_id, volume_id, slot_index, old_generation, old_row, new_row, confirmed
           FROM slot_write_intents WHERE request_id = ? AND confirmed = 0''',
        (request_id,),
    ).fetchone()
    return None if row is None else _intent_from_row(row)


def record_effective_write(db: sqlite3.Connection, intent: SlotWriteIntent) -> None:
    result = db.execute(
        '''UPDATE slot_write_intents SET confirmed = 1
           WHERE request_id = ? AND volume_id = ? AND slot_index = ? AND new_generation = ?
             AND old_row = ? AND new_row = ? AND confirmed = 0''',
        (
            intent.request_id, intent.volume_id, intent.slot_index, intent.new_generation,
            intent.old_row, intent.new_row,
        ),
    )
    if result.rowcount != 1:
        raise EvidenceError('the effective write does not match an unresolved intent')


def resolve_medium_layout(db: sqlite3.Connection, volume, slots) -> tuple[Basis, tuple[int, int, int]]:
    """Rebuild the layout actually on the medium from the write intents.

    The directory commits each intent before the medium write, and the two
    commits fail independently.  Replaying the intents over the sealed layout
    recovers the exact rows currently on the medium even when the write set is
    otherwise unreadable from the medium alone (the incident's (11, 11, 10)
    encodes a singular layout).  A confirmed intent landed.  An unconfirmed
    intent is settled by the slot generation: still the old generation means
    the write never landed; the new generation means it landed but its reply
    was lost.
    """
    rows = list(volume.initial_basis)
    generations = list(volume.initial_generations)
    physical = {slot.index: slot.generation for slot in slots}
    intents = db.execute(
        '''SELECT request_id, volume_id, slot_index, old_generation, new_generation,
                  old_row, new_row, confirmed
           FROM slot_write_intents WHERE volume_id = ?
           ORDER BY slot_index, old_generation''',
        (volume.volume_id,),
    ).fetchall()
    for row in intents:
        index = row['slot_index']
        if not row['confirmed']:
            actual = physical.get(index)
            if actual == row['old_generation']:
                continue
            if actual != row['new_generation']:
                raise EvidenceError(f'unexplained slot generation for {volume.volume_id}/{index}')
        if generations[index] != row['old_generation'] or rows[index] != row['old_row']:
            raise EvidenceError(f'inconsistent slot write history for {volume.volume_id}/{index}')
        generations[index] = row['new_generation']
        rows[index] = row['new_row']
    if tuple(generations) != tuple(physical.get(index) for index in range(3)):
        raise EvidenceError(f'medium has unacknowledged changes for {volume.volume_id}')
    try:
        basis = validate_basis(rows)
    except ValueError as exc:
        raise EvidenceError(
            f'medium no longer carries an invertible layout for {volume.volume_id}'
        ) from exc
    return basis, tuple(generations)
