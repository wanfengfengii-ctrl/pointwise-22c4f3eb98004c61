from dataclasses import dataclass
import json
import sqlite3

from errors import EvidenceError, UnknownVolume
from recording.provenance import Provenance, dump_provenance, load_provenance
from volume.basis import Basis, validate_basis


@dataclass(frozen=True, slots=True)
class VolumeRecord:
    volume_id: str
    medium_id: str
    recording_id: str
    stripe_length: int
    initial_basis: Basis
    initial_generations: tuple[int, int, int]
    provenance: Provenance


def publish_verified_volume(db: sqlite3.Connection, volume: VolumeRecord) -> None:
    db.execute(
        '''INSERT INTO volumes(volume_id, medium_id, recording_id, stripe_length,
                               initial_basis, initial_generations, provenance)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (
            volume.volume_id, volume.medium_id, volume.recording_id, volume.stripe_length,
            json.dumps(volume.initial_basis), json.dumps(volume.initial_generations),
            dump_provenance(volume.provenance),
        ),
    )


def get_verified_volume(db: sqlite3.Connection, volume_id: str) -> VolumeRecord:
    row = db.execute('SELECT * FROM volumes WHERE volume_id = ?', (volume_id,)).fetchone()
    if row is None:
        raise UnknownVolume(f'unknown verified volume: {volume_id}')
    try:
        basis = validate_basis(json.loads(row['initial_basis']))
        generations = tuple(json.loads(row['initial_generations']))
        if len(generations) != 3 or any(type(g) is not int or g < 0 for g in generations):
            raise ValueError('invalid initial slot generations')
    except (TypeError, ValueError) as exc:
        raise EvidenceError(f'invalid seal metadata for volume {volume_id}') from exc
    return VolumeRecord(
        volume_id, row['medium_id'], row['recording_id'], row['stripe_length'], basis, generations,
        load_provenance(row['provenance'], row['recording_id']),
    )
