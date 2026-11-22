from dataclasses import dataclass

from errors import require_text
from inspection.reconcile import ShiftObservation, build_shift_observation
from inspection.register import ShiftEntry, record_shift_entry
from storage import ArchiveStore


@dataclass(frozen=True, slots=True)
class ReconciledShift:
    entry: ShiftEntry
    observation: ShiftObservation


def reconcile_shift(
    store: ArchiveStore, shift_id: str, volume_id: str, request_id: str | None = None,
) -> ReconciledShift:
    require_text(shift_id, 'shift ID')
    require_text(volume_id, 'volume ID')
    if request_id is not None:
        require_text(request_id, 'request ID')
    with store.catalog(write=True) as db:
        observation = build_shift_observation(store, db, shift_id, volume_id, request_id)
        entry = record_shift_entry(db, observation)
    return ReconciledShift(entry, observation)
