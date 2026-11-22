import unittest

from errors import EvidenceError, InvalidInput, SlotReplyLost
from pickup.read import read_with_evidence
from recode.progress import SlotWriteIntent, record_intent
from recode.receipts import RecodeReceipt
from recode.requests import RecodeRequest, submit_recode
from tests.support import ArchiveCase, FINAL_SLOTS, STRIPES, TARGET
from volume.basis import validate_basis
from volume.slots import compare_and_write_slot


MARKER = 'WAVEFORM_RECODE_HANDOFF_MISMATCH'
# For this sample the seven nonzero masks have distinct one-byte encodings.
SAMPLE_MASKS = {7: 1, 11: 2, 12: 3, 13: 4, 10: 5, 6: 6, 1: 7}


def lose_committed_reply(event):
    if event.phase == 'after':
        raise SlotReplyLost('incident: slot committed and its reply was lost')


class HandoffIncident(ArchiveCase):
    def assert_pickup(self, source, case):
        try:
            pickup, evidence = read_with_evidence(self.store, 'volume')
        except EvidenceError as exc:
            self.fail(f'{MARKER} {case}: retired volume could not be picked up: {exc}')
        actual = tuple(list(stripe) for stripe in pickup.stripes)
        self.assertTrue(pickup.stripes == STRIPES, f'{MARKER} {case}: picked up {actual}; expected ([7], [11], [13])')
        self.assertEqual(pickup.provenance, source.provenance, f'{MARKER} {case}: provenance changed')
        return evidence

    def test_write_after_lost_reply(self):
        source, _ = self.make_volume()
        pending = submit_recode(self.store, 'volume', 'request', TARGET, on_boundary=lose_committed_reply)
        self.assertIsInstance(pending, RecodeRequest)
        self.reopen()
        self.assertIsNone(self.receipt())
        slots = self.slots()
        self.assertEqual(sum(slot.generation for slot in slots), 1)
        physical = tuple(slot.payload[0] for slot in slots)
        rows = tuple(SAMPLE_MASKS.get(value, 0) for value in physical)
        try:
            validate_basis(rows)
        except InvalidInput:
            self.fail(f'{MARKER} write: committed bytes {physical} encode singular layout {rows}')
        self.assert_pickup(source, 'write')
        receipt = submit_recode(self.store, 'volume', 'request', TARGET)
        self.assertIsInstance(receipt, RecodeReceipt)
        self.assertEqual(tuple(slot.payload for slot in self.slots()), FINAL_SLOTS)
        self.assertEqual(self.assert_pickup(source, 'final').basis, TARGET)
        self.reopen()
        self.assertEqual(submit_recode(self.store, 'volume', 'request', TARGET), receipt)

    def test_pickup_of_reversible_intermediate(self):
        source, volume = self.make_volume()
        pending = submit_recode(self.store, 'volume', 'request', TARGET, write_limit=0)
        self.assertIsInstance(pending, RecodeRequest)
        # Independently staged medium boundary, using the existing regression fixture interface.
        with self.store.catalog(write=True) as db:
            record_intent(db, SlotWriteIntent('request', 'volume', 2, 0, 5, 4))
        with self.assertRaises(SlotReplyLost):
            compare_and_write_slot(self.store, 'volume', volume.medium_id, 2, 0, b'\x0d',
                                   on_boundary=lose_committed_reply)
        self.reopen()
        self.assertIsNone(self.receipt())
        self.assertEqual(tuple(slot.payload for slot in self.slots()), STRIPES)
        evidence = self.assert_pickup(source, 'pickup')
        self.assertEqual(evidence.basis, (1, 2, 4), f'{MARKER} pickup: wrong intermediate layout')


if __name__ == '__main__':
    unittest.main()
