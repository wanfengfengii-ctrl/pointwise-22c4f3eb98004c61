from __future__ import annotations

from typing import TYPE_CHECKING

from pickup.decode import decode_original
from pickup.evidence import VolumeEvidence
from recode.layout import plan_slot_changes
from recode.progress import (
    SlotWriteIntent, record_effective_write, record_pending_intent, resolve_medium_layout,
)
from recode.receipts import RecodeReceipt, load_first_receipt
from recode.resume import settle_intents
from storage import ArchiveStore
from volume.basis import encode_row
from volume.catalog import get_verified_volume
from volume.slots import BoundaryHook, compare_and_write_slot, read_slots

if TYPE_CHECKING:
    from recode.requests import RecodeRequest


def _evidence(store: ArchiveStore, volume, db) -> VolumeEvidence:
    slots = read_slots(store, volume.volume_id, volume.medium_id)
    basis, _ = resolve_medium_layout(db, volume, slots)
    return VolumeEvidence(volume, slots, basis)


def apply_recode(
    store: ArchiveStore, request: RecodeRequest, *, write_limit: int | None = None,
    on_boundary: BoundaryHook | None = None,
) -> VolumeEvidence | RecodeReceipt | None:
    # The intent is committed to the directory before the medium is touched,
    # and the two commits fail independently.  Each step therefore uses its
    # own short catalog transaction so a lost reply cannot roll the evidence
    # away with the interrupted call.
    with store.catalog(write=True) as db:
        receipt = load_first_receipt(db, request.request_id)
        if receipt is not None:
            return receipt
        volume = get_verified_volume(db, request.volume_id)
        settle_intents(store, db, volume, request.request_id)
        published = _evidence(store, volume, db)

    steps = plan_slot_changes(published.basis, request.target)
    if not steps:
        return published
    original = decode_original(published.basis, published.payloads)
    batch = steps if write_limit is None else steps[:write_limit]

    for step in batch:
        index = step.slot_index
        generation = published.slots[index].generation
        payload = encode_row(step.new_row, original)
        write = SlotWriteIntent(request.request_id, volume.volume_id, index, generation,
                                step.old_row, step.new_row)
        with store.catalog(write=True) as db:
            record_pending_intent(db, write)
        compare_and_write_slot(store, volume.volume_id, volume.medium_id, index, generation,
                               payload, on_boundary=on_boundary)
        with store.catalog(write=True) as db:
            record_effective_write(db, write)
        with store.catalog() as db:
            published = _evidence(store, volume, db)

    if len(batch) < len(steps):
        return None
    with store.catalog() as db:
        final = _evidence(store, volume, db)
    if final.basis != request.target:
        return None
    return final
