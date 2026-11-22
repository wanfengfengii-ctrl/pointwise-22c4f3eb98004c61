from errors import ConflictError, EvidenceError, require_text
from pickup.read import read_with_evidence
from recording.provenance import Provenance
from recording.sources import commit_retirement, load_readable_recording
from storage import ArchiveStore
from volume.catalog import get_verified_volume


def retire_recording(store: ArchiveStore, recording_id: str, volume_id: str) -> Provenance:
    require_text(recording_id, 'recording ID')
    require_text(volume_id, 'volume ID')
    with store.catalog(write=True) as db:
        source = load_readable_recording(db, recording_id)
        volume = get_verified_volume(db, volume_id)
        if volume.recording_id != recording_id:
            raise ConflictError('verified volume belongs to a different recording')
        pickup, _ = read_with_evidence(store, volume_id, db=db)
        if pickup.stripes != source.stripes or pickup.provenance != source.provenance:
            raise EvidenceError('volume does not match the source recording')
        commit_retirement(db, recording_id, volume_id)
    return source.provenance
