from dataclasses import dataclass
import sqlite3

from errors import ConflictError
from inspection.receipts import verified_receipt_for_shift
from pickup.read import read_with_evidence
from pickup.result import PickupResult
from recode.receipts import RecodeReceipt
from recode.requests import get_request
from storage import ArchiveStore
from volume.basis import Basis


@dataclass(frozen=True, slots=True)
class ShiftObservation:
    shift_id: str
    pickup: PickupResult
    basis: Basis
    generations: tuple[int, int, int]
    request_id: str | None
    status: str
    receipt: RecodeReceipt | None


def build_shift_observation(
    store: ArchiveStore, db: sqlite3.Connection, shift_id: str, volume_id: str, request_id: str | None,
) -> ShiftObservation:
    request = None if request_id is None else get_request(db, request_id)
    if request is not None and request.volume_id != volume_id:
        raise ConflictError('shift request belongs to a different volume')
    pickup, evidence = read_with_evidence(store, volume_id, db=db)
    receipt = None if request is None else verified_receipt_for_shift(db, request)
    return ShiftObservation(
        shift_id, pickup, evidence.basis, evidence.generations, request_id,
        'available' if request is None else request.status, receipt,
    )
