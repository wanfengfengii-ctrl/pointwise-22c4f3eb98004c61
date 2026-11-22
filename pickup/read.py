import sqlite3

from errors import require_text
from pickup.decode import decode_original
from pickup.evidence import VolumeEvidence, collect_volume_evidence
from pickup.result import PickupResult, make_pickup_result
from storage import ArchiveStore
from volume.catalog import get_verified_volume


def read_with_evidence(
    store: ArchiveStore, volume_id: str, *, db: sqlite3.Connection | None = None,
) -> tuple[PickupResult, VolumeEvidence]:
    require_text(volume_id, 'volume ID')
    if db is None:
        with store.catalog() as catalog:
            volume = get_verified_volume(catalog, volume_id)
    else:
        volume = get_verified_volume(db, volume_id)
    evidence = collect_volume_evidence(store, volume, db=db)
    original = decode_original(evidence.basis, evidence.payloads)
    return make_pickup_result(volume, original), evidence


def read_volume(store: ArchiveStore, volume_id: str) -> PickupResult:
    result, _ = read_with_evidence(store, volume_id)
    return result
