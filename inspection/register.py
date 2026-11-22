from dataclasses import dataclass
from hashlib import sha256
import json
import sqlite3

from inspection.reconcile import ShiftObservation
from recording.provenance import Provenance, dump_provenance, load_provenance
from volume.basis import Basis


@dataclass(frozen=True, slots=True)
class ShiftEntry:
    entry_id: int
    shift_id: str
    volume_id: str
    recording_id: str
    provenance: Provenance
    stripe_digests: tuple[str, str, str]
    basis: Basis
    generations: tuple[int, int, int]
    request_id: str | None
    status: str
    receipt_id: str | None


def record_shift_entry(db: sqlite3.Connection, observation: ShiftObservation) -> ShiftEntry:
    pickup = observation.pickup
    digests = tuple(sha256(stripe).hexdigest() for stripe in pickup.stripes)
    receipt_id = None if observation.receipt is None else observation.receipt.receipt_id
    result = db.execute(
        '''INSERT INTO shift_entries(shift_id, volume_id, recording_id, provenance, stripe_digests,
                                     basis, generations, request_id, status, receipt_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            observation.shift_id, pickup.volume_id, pickup.recording_id, dump_provenance(pickup.provenance),
            json.dumps(digests), json.dumps(observation.basis), json.dumps(observation.generations),
            observation.request_id, observation.status, receipt_id,
        ),
    )
    return ShiftEntry(
        result.lastrowid, observation.shift_id, pickup.volume_id, pickup.recording_id, pickup.provenance,
        digests, observation.basis, observation.generations, observation.request_id, observation.status,
        receipt_id,
    )


def list_shift_entries(db: sqlite3.Connection) -> tuple[ShiftEntry, ...]:
    rows = db.execute('SELECT * FROM shift_entries ORDER BY entry_id')
    return tuple(
        ShiftEntry(
            row['entry_id'], row['shift_id'], row['volume_id'], row['recording_id'],
            load_provenance(row['provenance'], row['recording_id']), tuple(json.loads(row['stripe_digests'])),
            tuple(json.loads(row['basis'])), tuple(json.loads(row['generations'])), row['request_id'],
            row['status'], row['receipt_id'],
        )
        for row in rows
    )
