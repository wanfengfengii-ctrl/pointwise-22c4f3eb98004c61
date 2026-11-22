from dataclasses import dataclass
from datetime import datetime
import json
import sqlite3

from errors import ConflictError, EvidenceError, InvalidInput, SlotReplyLost, UnknownRequest, require_text
from pickup.evidence import collect_volume_evidence
from recode.apply import apply_recode
from recode.receipts import RecodeReceipt, issue_first_receipt, load_first_receipt, receipt_time
from storage import ArchiveStore
from volume.basis import Basis, validate_basis
from volume.catalog import get_verified_volume
from volume.slots import BoundaryHook


@dataclass(frozen=True, slots=True)
class RecodeRequest:
    request_id: str
    volume_id: str
    target: Basis
    status: str


def get_request(db: sqlite3.Connection, request_id: str) -> RecodeRequest:
    row = db.execute('SELECT * FROM recode_requests WHERE request_id = ?', (request_id,)).fetchone()
    if row is None:
        raise UnknownRequest(f'unknown recode request: {request_id}')
    return RecodeRequest(request_id, row['volume_id'], tuple(json.loads(row['target'])), row['status'])


def _admit_request(db: sqlite3.Connection, store: ArchiveStore, volume_id: str, request_id: str, target: Basis):
    try:
        request = get_request(db, request_id)
    except UnknownRequest:
        volume = get_verified_volume(db, volume_id)
        active = db.execute(
            "SELECT request_id FROM recode_requests WHERE volume_id = ? AND status = 'pending'", (volume_id,)
        ).fetchone()
        if active is not None:
            raise ConflictError(f'volume already has pending request {active["request_id"]}')
        collect_volume_evidence(store, volume, db=db)
        db.execute(
            "INSERT INTO recode_requests(request_id, volume_id, target, status) VALUES (?, ?, ?, 'pending')",
            (request_id, volume_id, json.dumps(target)),
        )
        return RecodeRequest(request_id, volume_id, target, 'pending')
    if request.volume_id != volume_id or request.target != target:
        raise ConflictError(f'request ID has different parameters: {request_id}')
    return request


def _request_result(db: sqlite3.Connection, request: RecodeRequest) -> RecodeRequest | RecodeReceipt:
    receipt = load_first_receipt(db, request.request_id)
    if request.status == 'done':
        if receipt is None or receipt.volume_id != request.volume_id or receipt.target != request.target:
            raise EvidenceError('completed request has no matching first receipt')
        return receipt
    if receipt is not None:
        raise EvidenceError('pending request already has a receipt')
    return request


def submit_recode(
    store: ArchiveStore, volume_id: str, request_id: str, target,
    *, write_limit: int | None = None, on_boundary: BoundaryHook | None = None,
    issued_at: datetime | None = None,
) -> RecodeRequest | RecodeReceipt:
    require_text(volume_id, 'volume ID')
    require_text(request_id, 'request ID')
    target = validate_basis(target)
    if write_limit is not None and (type(write_limit) is not int or write_limit < 0):
        raise InvalidInput('write_limit must be a nonnegative integer')
    stamp = None if issued_at is None else receipt_time(issued_at)
    with store.catalog(write=True) as db:
        request = _admit_request(db, store, volume_id, request_id, target)
        current = _request_result(db, request)
    if isinstance(current, RecodeReceipt):
        return current

    try:
        terminal = apply_recode(store, request, write_limit=write_limit, on_boundary=on_boundary)
    except SlotReplyLost:
        terminal = None
    if terminal is None or isinstance(terminal, RecodeReceipt):
        with store.catalog() as db:
            return _request_result(db, get_request(db, request_id))

    with store.catalog(write=True) as db:
        current = _request_result(db, get_request(db, request_id))
        if isinstance(current, RecodeReceipt):
            return current
        receipt = issue_first_receipt(db, request_id, volume_id, target, terminal, stamp=stamp)
        db.execute("UPDATE recode_requests SET status = 'done' WHERE request_id = ?", (request_id,))
        return receipt
