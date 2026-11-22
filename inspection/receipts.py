import sqlite3

from errors import EvidenceError
from recode.receipts import RecodeReceipt, load_first_receipt
from recode.requests import RecodeRequest


def verified_receipt_for_shift(db: sqlite3.Connection, request: RecodeRequest) -> RecodeReceipt | None:
    receipt = load_first_receipt(db, request.request_id)
    if request.status == 'pending' and receipt is None:
        return None
    if (
        request.status != 'done' or receipt is None or receipt.request_id != request.request_id
        or receipt.volume_id != request.volume_id or receipt.target != request.target
    ):
        raise EvidenceError('request and first receipt disagree in the shift observation')
    return receipt
