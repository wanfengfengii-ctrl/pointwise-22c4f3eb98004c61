import sqlite3

from errors import EvidenceError
from storage import ArchiveStore
from volume.slots import read_slots


def settle_intents(
    store: ArchiveStore, db: sqlite3.Connection, volume, request_id: str,
) -> None:
    """Resolve intents left unconfirmed by an interrupted attempt.

    The intent is committed to the directory before the medium is touched, so
    after a reopen the slot generation alone tells what happened.  A slot that
    reached the new generation confirms the write even though the reply was
    lost; a slot still at the old generation discards the intent.  The update
    is idempotent, so a crash between the medium commit and this call is safe.
    """
    slots = read_slots(store, volume.volume_id, volume.medium_id)
    physical = {slot.index: slot.generation for slot in slots}
    rows = db.execute(
        '''SELECT request_id, slot_index, old_generation, new_generation
           FROM slot_write_intents WHERE volume_id = ? AND confirmed = 0''',
        (volume.volume_id,),
    ).fetchall()
    for row in rows:
        if row['request_id'] != request_id:
            raise EvidenceError(
                f'staged slot write belongs to another request: {row["request_id"]}'
            )
        index = row['slot_index']
        actual = physical.get(index)
        if actual == row['new_generation']:
            db.execute(
                '''UPDATE slot_write_intents SET confirmed = 1
                   WHERE volume_id = ? AND slot_index = ? AND new_generation = ? AND confirmed = 0''',
                (volume.volume_id, index, row['new_generation']),
            )
        elif actual == row['old_generation']:
            db.execute(
                '''DELETE FROM slot_write_intents
                   WHERE volume_id = ? AND slot_index = ? AND new_generation = ? AND confirmed = 0''',
                (volume.volume_id, index, row['new_generation']),
            )
        else:
            raise EvidenceError(f'unexplained medium generation for {volume.volume_id}/{index}')
