from dataclasses import dataclass
import sqlite3

from errors import EvidenceError


@dataclass(frozen=True, slots=True)
class SlotWriteIntent:
    request_id: str
    volume_id: str
    slot_index: int
    old_generation: int
    old_row: int
    new_row: int

    @property
    def new_generation(self) -> int:
        return self.old_generation + 1


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


def find_pending_intent(db: sqlite3.Connection, request_id: str) -> SlotWriteIntent | None:
    row = db.execute(
        '''SELECT request_id, volume_id, slot_index, old_generation, old_row, new_row
           FROM slot_write_intents WHERE request_id = ? AND confirmed = 0''',
        (request_id,),
    ).fetchone()
    return None if row is None else SlotWriteIntent(**dict(row))


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


def acknowledged_writes(db: sqlite3.Connection, request_id: str) -> tuple[SlotWriteIntent, ...]:
    rows = db.execute(
        '''SELECT request_id, volume_id, slot_index, old_generation, old_row, new_row
           FROM slot_write_intents WHERE request_id = ? AND confirmed = 1
           ORDER BY slot_index, new_generation''',
        (request_id,),
    )
    return tuple(SlotWriteIntent(**dict(row)) for row in rows)
