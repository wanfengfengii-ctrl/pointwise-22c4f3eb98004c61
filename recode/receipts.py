from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from uuid import uuid4

from errors import EvidenceError, InvalidInput
from pickup.evidence import VolumeEvidence
from volume.basis import Basis


@dataclass(frozen=True, slots=True)
class RecodeReceipt:
    request_id: str
    receipt_id: str
    volume_id: str
    issued_at: str
    target: Basis
    generations: tuple[int, int, int]
    checksums: tuple[str, str, str]


def receipt_time(issued_at: datetime) -> str:
    if not isinstance(issued_at, datetime) or issued_at.utcoffset() is None:
        raise InvalidInput('receipt time must be timezone-aware')
    return issued_at.astimezone(timezone.utc).isoformat(timespec='microseconds')


def issue_first_receipt(
    db: sqlite3.Connection, request_id: str, volume_id: str, target: Basis,
    evidence: VolumeEvidence, *, stamp: str | None = None,
) -> RecodeReceipt:
    if evidence.volume.volume_id != volume_id or evidence.basis != target:
        raise EvidenceError('physical target is not ready for a receipt')
    receipt = RecodeReceipt(
        request_id, uuid4().hex, volume_id, stamp or receipt_time(datetime.now(timezone.utc)),
        target, evidence.generations, evidence.checksums,
    )
    db.execute(
        '''INSERT INTO recode_receipts(request_id, receipt_id, volume_id, issued_at,
                                       target, generations, checksums) VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (
            receipt.request_id, receipt.receipt_id, receipt.volume_id, receipt.issued_at,
            json.dumps(receipt.target), json.dumps(receipt.generations), json.dumps(receipt.checksums),
        ),
    )
    return receipt


def load_first_receipt(db: sqlite3.Connection, request_id: str) -> RecodeReceipt | None:
    row = db.execute('SELECT * FROM recode_receipts WHERE request_id = ?', (request_id,)).fetchone()
    if row is None:
        return None
    return RecodeReceipt(
        row['request_id'], row['receipt_id'], row['volume_id'], row['issued_at'],
        tuple(json.loads(row['target'])), tuple(json.loads(row['generations'])),
        tuple(json.loads(row['checksums'])),
    )
