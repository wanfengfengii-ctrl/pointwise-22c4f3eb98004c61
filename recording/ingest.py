from errors import require_text
from recording.channels import validate_channels
from recording.provenance import order_provenance
from recording.sources import SourceRecording, store_recording
from storage import ArchiveStore


def accept_recording(store: ArchiveStore, recording_id: str, channels) -> SourceRecording:
    require_text(recording_id, 'recording ID')
    ordered = validate_channels(channels)
    provenance = order_provenance(recording_id, ordered)
    recording = SourceRecording(recording_id, ordered, provenance)
    with store.catalog(write=True) as db:
        store_recording(db, recording)
    return recording
