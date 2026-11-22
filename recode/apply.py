from __future__ import annotations

from typing import TYPE_CHECKING

from pickup.decode import decode_original
from pickup.evidence import VolumeEvidence, collect_volume_evidence
from recode.layout import plan_slot_changes
from recode.progress import SlotWriteIntent, record_effective_write, record_intent
from recode.receipts import RecodeReceipt, load_first_receipt
from recode.resume import acknowledged_view
from storage import ArchiveStore
from volume.basis import encode_row
from volume.catalog import get_verified_volume
from volume.slots import BoundaryHook, compare_and_write_slot

if TYPE_CHECKING:
    from recode.requests import RecodeRequest


def apply_recode(
    store: ArchiveStore, request: RecodeRequest, *, write_limit: int | None = None,
    on_boundary: BoundaryHook | None = None,
) -> VolumeEvidence | RecodeReceipt | None:
    with store.catalog(write=True) as db:
        receipt = load_first_receipt(db, request.request_id)
        if receipt is not None:
            return receipt
        volume = get_verified_volume(db, request.volume_id)
        published = collect_volume_evidence(store, volume, db=db)
        current = acknowledged_view(db, published, request.request_id)
        steps = plan_slot_changes(current.basis, request.target)
        if not steps:
            return current
        original = decode_original(current.basis, current.payloads)
        batch = steps[:write_limit]
        for step in batch:
            index = step.slot_index
            generation = current.slots[index].generation
            payload = encode_row(step.new_row, original)
            compare_and_write_slot(store, volume.volume_id, volume.medium_id, index, generation,
                                   payload, on_boundary=on_boundary)
            write = SlotWriteIntent(request.request_id, volume.volume_id, index, generation,
                                    step.old_row, step.new_row)
            record_intent(db, write)
            record_effective_write(db, write)
        if len(batch) < len(steps):
            return None
        published = collect_volume_evidence(store, volume, db=db)
        return acknowledged_view(db, published, request.request_id)
