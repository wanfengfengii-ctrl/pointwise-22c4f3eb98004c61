import unittest

from errors import EvidenceError, InvalidInput, SlotReplyLost
from pickup.decode import decode_original
from pickup.read import read_with_evidence
from recode.progress import SlotWriteIntent, record_intent
from recode.receipts import RecodeReceipt
from recode.requests import RecodeRequest, submit_recode
from storage import ArchiveStore
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

    def test_pickup_at_every_pause_point(self):
        # Lose the reply after the committed write that lands on each pause
        # point of a fresh run, reopen, and pick the volume up by its original
        # number.  Every planned step must leave the medium invertible.
        for pause in range(1, 5):
            with self.subTest(pause=pause):
                self._fresh_case(pause)
                source, _ = self.make_volume(
                    recording_id=f'pause-recording-{pause}', volume_id=f'pause-volume-{pause}')
                volume_id, request_id = f'pause-volume-{pause}', f'pause-request-{pause}'
                commits = []

                def lose_after_commit(event, pause=pause):
                    if event.phase == 'after':
                        commits.append(event)
                        if len(commits) == pause:
                            raise SlotReplyLost(f'pause {pause}')

                pending = submit_recode(self.store, volume_id, request_id, TARGET,
                                        on_boundary=lose_after_commit)
                self.assertIsInstance(pending, RecodeRequest)
                self.reopen()
                self.assertIsNone(self.receipt(request_id))
                pickup, evidence = read_with_evidence(self.store, volume_id)
                self.assertEqual(pickup.stripes, STRIPES)
                self.assertEqual(pickup.provenance, source.provenance)
                self.assertEqual(decode_original(evidence.basis, evidence.payloads), STRIPES)
                receipt = submit_recode(self.store, volume_id, request_id, TARGET)
                self.assertIsInstance(receipt, RecodeReceipt)
                self.assertEqual(tuple(slot.payload for slot in self.slots(volume_id)), FINAL_SLOTS)
                self.reopen()
                self.assertEqual(submit_recode(self.store, volume_id, request_id, TARGET), receipt)

    def test_pause_visible_slot_bytes(self):
        # Incident write case: one committed slot plus a lost reply must still
        # be readable, and the committed slot must have advanced the layout.
        source, _ = self.make_volume()
        submit_recode(self.store, 'volume', 'request', TARGET, on_boundary=lose_committed_reply)
        self.reopen()
        slots = self.slots()
        self.assertEqual(sum(slot.generation for slot in slots), 1)
        evidence = self.assert_pickup(source, 'write-bytes')
        self.assertNotEqual(evidence.basis, (1, 2, 5))
        self.assertEqual(decode_original(evidence.basis, evidence.payloads), STRIPES)

    def _fresh_case(self, tag):
        self.root = self.root / str(tag)
        self.root.mkdir()
        self.store = ArchiveStore(self.root)

    def test_equal_bytes_still_advance(self):
        # Zero stripes encode to zero for every row, so a layout change rewrites
        # identical bytes.  The generation, not the bytes, decides whether the
        # lost write landed.
        zeros = (b'\x00', b'\x00', b'\x00')
        self.make_volume(stripes=zeros)
        pending = submit_recode(self.store, 'volume', 'request', TARGET,
                                on_boundary=lose_committed_reply)
        self.assertIsInstance(pending, RecodeRequest)
        self.reopen()
        pickup, evidence = read_with_evidence(self.store, 'volume')
        self.assertEqual(pickup.stripes, zeros)
        self.assertEqual(evidence.payloads, zeros)
        self.assertEqual(evidence.basis, (3, 2, 5))
        receipt = submit_recode(self.store, 'volume', 'request', TARGET)
        self.assertIsInstance(receipt, RecodeReceipt)
        self.assertEqual(tuple(slot.payload for slot in self.slots()), zeros)
        self.assertEqual(tuple(slot.generation for slot in self.slots()), receipt.generations)

    def test_empty_stripes_each_pause(self):
        for phase in ('before', 'after'):
            with self.subTest(phase=phase):
                self._fresh_case(f'empty-{phase}')
                volume_id, request_id = f'empty-volume-{phase}', f'empty-request-{phase}'
                empty = (b'', b'', b'')
                self.make_volume(recording_id=f'empty-recording-{phase}', volume_id=volume_id,
                                 stripes=empty)

                def lose(event, phase=phase):
                    if event.phase == phase:
                        raise SlotReplyLost(phase)

                pending = submit_recode(self.store, volume_id, request_id, TARGET,
                                        on_boundary=lose)
                self.assertIsInstance(pending, RecodeRequest)
                self.reopen()
                pickup, evidence = read_with_evidence(self.store, volume_id)
                self.assertEqual(pickup.stripes, empty)
                self.assertEqual(evidence.payloads, empty)
                self.assertEqual(evidence.basis, (1, 2, 5) if phase == 'before' else (3, 2, 5))
                receipt = submit_recode(self.store, volume_id, request_id, TARGET)
                self.assertIsInstance(receipt, RecodeReceipt)
                self.assertEqual(tuple(slot.payload for slot in self.slots(volume_id)), empty)

if __name__ == '__main__':
    unittest.main()
