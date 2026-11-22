from datetime import datetime, timezone
from hashlib import sha256

from errors import ConflictError
from inspection.shifts import reconcile_shift
from pickup.read import read_volume, read_with_evidence
from recode.receipts import RecodeReceipt
from recode.requests import RecodeRequest, submit_recode
from tests.support import ArchiveCase, INITIAL, STRIPES, TARGET


class InspectionTests(ArchiveCase):
    def test_reconcile_pending_and_done(self):
        source, _ = self.make_volume()
        started = submit_recode(self.store, 'volume', 'request', TARGET, write_limit=1)
        self.assertIsInstance(started, RecodeRequest)
        _, pending_view = read_with_evidence(self.store, 'volume')
        pending = reconcile_shift(self.store, 'night', 'volume', 'request')
        self.assertEqual(pending.entry.status, 'pending')
        self.assertEqual(pending.entry.basis, pending_view.basis)
        self.assertEqual(pending.entry.generations, pending_view.generations)
        self.assertIsNone(pending.entry.receipt_id)
        self.assertIsNone(pending.observation.receipt)
        self.assertEqual(pending.observation.pickup.stripes, STRIPES)
        self.assertEqual(pending.entry.provenance, source.provenance)
        receipt = submit_recode(self.store, 'volume', 'request', TARGET)
        done = reconcile_shift(self.store, 'morning', 'volume', 'request')
        self.assertEqual(done.entry.status, 'done')
        self.assertEqual(done.entry.basis, TARGET)
        self.assertEqual(done.entry.generations, receipt.generations)
        self.assertEqual(done.entry.receipt_id, receipt.receipt_id)
        self.assertEqual(done.observation.receipt, receipt)
        self.assertEqual(done.observation.pickup, pending.observation.pickup)
        self.assertEqual(done.entry.stripe_digests, tuple(sha256(data).hexdigest() for data in STRIPES))
        self.assertEqual(self.shifts(), (pending.entry, done.entry))

    def test_replay_receipt(self):
        self.make_volume()
        first = submit_recode(self.store, 'volume', 'request', TARGET)
        self.assertIsInstance(first, RecodeReceipt)
        entry = reconcile_shift(self.store, 'morning', 'volume', 'request').entry
        slots = self.slots()
        self.reopen()
        self.assertEqual(submit_recode(self.store, 'volume', 'request', TARGET), first)
        with self.assertRaises(ConflictError):
            submit_recode(self.store, 'volume', 'request', INITIAL)
        self.assertEqual(self.receipt(), first)
        self.assertEqual(self.slots(), slots)
        self.assertEqual(self.shifts(), (entry,))
        self.assertEqual(read_volume(self.store, 'volume').stripes, STRIPES)

    def test_same_request_first_receipt(self):
        self.make_volume()
        first_time = datetime(2025, 1, 10, 9, 0, tzinfo=timezone.utc)
        second_time = datetime(2025, 1, 10, 11, 0, tzinfo=timezone.utc)
        first = submit_recode(self.store, 'volume', 'request', TARGET, issued_at=first_time)
        morning = reconcile_shift(self.store, 'morning', 'volume', 'request').entry
        submit_recode(self.store, 'volume', 'later', INITIAL, issued_at=second_time)
        slots = self.slots()
        self.reopen()
        replay = submit_recode(self.store, 'volume', 'request', TARGET, issued_at=second_time)
        self.assertEqual(replay, first)
        self.assertEqual(replay.issued_at, '2025-01-10T09:00:00.000000+00:00')
        self.assertEqual(morning.receipt_id, replay.receipt_id)
        self.assertEqual(self.slots(), slots)
        self.assertEqual(self.shifts(), (morning,))
        later_observation = reconcile_shift(self.store, 'later-lookup', 'volume', 'request')
        self.assertEqual(later_observation.observation.receipt, first)
        self.assertEqual(later_observation.entry.basis, INITIAL)

    def test_request_volume_mismatch(self):
        self.make_volume()
        self.make_volume(recording_id='other', volume_id='other-volume', stripes=(b'a', b'b', b'c'))
        receipt = submit_recode(self.store, 'other-volume', 'request', INITIAL)
        self.assertIsInstance(receipt, RecodeReceipt)
        initial = reconcile_shift(self.store, 'morning', 'volume').entry
        with self.assertRaises(ConflictError):
            reconcile_shift(self.store, 'wrong-pair', 'volume', 'request')
        self.assertEqual(self.shifts(), (initial,))
        self.assertEqual(self.receipt(), receipt)
        correct = reconcile_shift(self.store, 'right-pair', 'other-volume', 'request')
        self.assertEqual(correct.observation.pickup.stripes, (b'a', b'b', b'c'))
        self.assertEqual(correct.entry.receipt_id, receipt.receipt_id)
