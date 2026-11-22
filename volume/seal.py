from collections.abc import Callable
from uuid import uuid4

from errors import ConflictError, EvidenceError, require_text
from pickup.decode import decode_original
from recording.sources import load_readable_recording
from storage import ArchiveStore
from volume.basis import encode_stripes, validate_basis
from volume.catalog import VolumeRecord, publish_verified_volume
from volume.slots import discard_unpublished_slots, initialize_slots, read_slots


def seal_volume(
    store: ArchiveStore, recording_id: str, volume_id: str, basis,
    *, after_slots: Callable[[str], None] | None = None,
) -> VolumeRecord:
    require_text(recording_id, 'recording ID')
    require_text(volume_id, 'volume ID')
    basis = validate_basis(basis)
    with store.catalog(write=True) as db:
        if db.execute('SELECT 1 FROM volumes WHERE volume_id = ?', (volume_id,)).fetchone() is not None:
            raise ConflictError(f'volume already exists: {volume_id}')
        source = load_readable_recording(db, recording_id)
        payloads = encode_stripes(basis, source.stripes)
        medium_id = uuid4().hex
        discard_unpublished_slots(store, volume_id)
        initialize_slots(store, volume_id, medium_id, payloads)
        try:
            if after_slots is not None:
                after_slots(medium_id)
            slots = read_slots(store, volume_id, medium_id)
            if decode_original(basis, tuple(slot.payload for slot in slots)) != source.stripes:
                raise EvidenceError('sealed medium did not reproduce the recording')
            volume = VolumeRecord(
                volume_id, medium_id, recording_id, len(source.stripes[0]), basis,
                tuple(slot.generation for slot in slots), source.provenance,
            )
            publish_verified_volume(db, volume)
        except Exception:
            discard_unpublished_slots(store, volume_id)
            raise
    return volume
