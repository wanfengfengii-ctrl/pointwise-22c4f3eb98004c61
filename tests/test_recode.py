from errors import ConflictError, EvidenceError, InvalidInput, SlotReplyLost, UnknownRequest
from pickup.read import read_volume, read_with_evidence
from recode.progress import SlotWriteIntent, find_pending_intent, record_intent
from recode.receipts import RecodeReceipt
from recode.requests import RecodeRequest, submit_recode
from tests.support import ArchiveCase, FINAL_SLOTS, INITIAL, STRIPES, TARGET
from volume.slots import compare_and_write_slot


class RecodeTests(ArchiveCase):
    def test_read_each_boundary(self):
        source, _ = self.make_volume()
        observed = []

        def inspect_commit(event):
            if event.phase == 'after':
                pickup, evidence = read_with_evidence(self.store, 'volume')
                self.assertEqual(pickup.stripes, STRIPES)
                self.assertEqual(pickup.provenance, source.provenance)
                self.assertEqual(evidence.slots[event.snapshot.index], event.snapshot)
                self.assertIsNone(self.receipt())
                observed.append(evidence.generations)

        receipt = submit_recode(self.store, 'volume', 'request', TARGET, on_boundary=inspect_commit)
        self.assertIsInstance(receipt, RecodeReceipt)
        self.assertGreater(len(observed), 1)
        previous = (0, 0, 0)
        for generations in observed:
            self.assertEqual(sorted(new - old for new, old in zip(generations, previous, strict=True)), [0, 0, 1])
            previous = generations
        self.assertEqual(receipt.generations, observed[-1])
        self.assertEqual(receipt.target, TARGET)
        self.assertEqual(tuple(s.payload for s in self.slots()), FINAL_SLOTS)
        self.assertEqual(receipt.checksums, tuple(s.checksum for s in self.slots()))
        self.assertEqual(read_volume(self.store, 'volume').stripes, STRIPES)

    def test_intermediate_pickup(self):
        source, volume = self.make_volume()
        request = submit_recode(self.store, 'volume', 'request', TARGET, write_limit=0)
        self.assertIsInstance(request, RecodeRequest)
        intent = SlotWriteIntent('request', 'volume', 2, 0, 5, 4)
        with self.store.catalog(write=True) as db:
            record_intent(db, intent)

        def lose_reply(event):
            if event.phase == 'after':
                raise SlotReplyLost('independent medium fixture lost its reply')

        with self.assertRaises(SlotReplyLost):
            compare_and_write_slot(self.store, 'volume', volume.medium_id, 2, 0, b'\x0d', on_boundary=lose_reply)
        self.reopen()
        self.assertEqual(tuple(s.payload for s in self.slots()), STRIPES)
        self.assertEqual(self.request().status, 'pending')
        self.assertIsNone(self.receipt())
        pickup, evidence = read_with_evidence(self.store, 'volume')
        self.assertEqual(evidence.basis, (1, 2, 4))
        self.assertEqual(pickup.stripes, STRIPES)
        self.assertEqual(pickup.provenance, source.provenance)
        with self.store.catalog() as db:
            self.assertEqual(find_pending_intent(db, 'request'), intent)

    def test_lost_reply(self):
        for phase in ('before', 'after'):
            with self.subTest(phase=phase):
                volume_id, request_id = f'volume-{phase}', f'request-{phase}'
                source, _ = self.make_volume(recording_id=f'recording-{phase}', volume_id=volume_id)
                attempts = []

                def lose_reply(event):
                    if event.phase == phase:
                        attempts.append(event)
                        raise SlotReplyLost(phase)

                result = submit_recode(self.store, volume_id, request_id, TARGET, on_boundary=lose_reply)
                self.assertIsInstance(result, RecodeRequest)
                self.assertEqual(len(attempts), 1)
                self.assertIsNone(self.receipt(request_id))
                self.reopen()
                pickup, view = read_with_evidence(self.store, volume_id)
                self.assertEqual(pickup.stripes, STRIPES)
                self.assertEqual(pickup.provenance, source.provenance)
                attempted = attempts[0]
                actual_slot = view.slots[attempted.snapshot.index]
                expected_generation = attempted.previous_generation if phase == 'before' else attempted.snapshot.generation
                self.assertEqual(actual_slot.generation, expected_generation)
                with self.assertRaises(ConflictError):
                    submit_recode(self.store, volume_id, request_id, (1, 2, 4))
                self.assertEqual(read_volume(self.store, volume_id), pickup)
                completed = submit_recode(self.store, volume_id, request_id, TARGET)
                self.assertIsInstance(completed, RecodeReceipt)
                self.assertEqual(tuple(s.payload for s in self.slots(volume_id)), FINAL_SLOTS)
                self.assertEqual(submit_recode(self.store, volume_id, request_id, TARGET), completed)

    def test_zero_payload_generation(self):
        zeros = (b'\x00', b'\x00', b'\x00')
        target = (1, 2, 4)
        for phase in ('before', 'after'):
            with self.subTest(phase=phase):
                volume_id = f'zero-{phase}'
                self.make_volume(recording_id=f'source-{phase}', volume_id=volume_id, stripes=zeros)

                def lose_reply(event):
                    if event.phase == phase:
                        self.assertEqual(event.snapshot.payload, b'\x00')
                        raise SlotReplyLost(phase)

                pending = submit_recode(self.store, volume_id, phase, target, on_boundary=lose_reply)
                self.assertIsInstance(pending, RecodeRequest)
                self.reopen()
                pickup, evidence = read_with_evidence(self.store, volume_id)
                self.assertEqual(pickup.stripes, zeros)
                self.assertEqual(evidence.payloads, zeros)
                expected_generations = (0, 0, 0) if phase == 'before' else (0, 0, 1)
                self.assertEqual(evidence.generations, expected_generations)
                self.assertEqual(evidence.basis, INITIAL if phase == 'before' else target)
                self.assertIsNone(self.receipt(phase))
                attempts = []
                receipt = submit_recode(self.store, volume_id, phase, target, on_boundary=attempts.append)
                self.assertIsInstance(receipt, RecodeReceipt)
                self.assertEqual(receipt.generations, (0, 0, 1))
                self.assertEqual([event.phase for event in attempts], ['before', 'after'] if phase == 'before' else [])
                self.assertEqual(self.receipt(phase), receipt)

    def test_receipt_after_durable_target(self):
        self.make_volume()

        def lose_last_before(event):
            if event.phase == 'before':
                projected = [slot.payload for slot in self.slots()]
                projected[event.snapshot.index] = event.snapshot.payload
                if tuple(projected) == FINAL_SLOTS:
                    raise SlotReplyLost('last slot did not commit')

        pending = submit_recode(self.store, 'volume', 'request', TARGET, on_boundary=lose_last_before)
        self.assertIsInstance(pending, RecodeRequest)
        self.reopen()
        self.assertEqual(self.request().status, 'pending')
        self.assertIsNone(self.receipt())
        self.assertNotEqual(tuple(s.payload for s in self.slots()), FINAL_SLOTS)
        self.assertEqual(read_volume(self.store, 'volume').stripes, STRIPES)
        receipt = submit_recode(self.store, 'volume', 'request', TARGET)
        self.assertIsInstance(receipt, RecodeReceipt)
        self.assertEqual(tuple(s.payload for s in self.slots()), FINAL_SLOTS)
        with self.store.catalog() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM recode_receipts').fetchone()[0], 1)

    def test_singular_target(self):
        self.make_volume()
        before = self.slots()
        with self.assertRaises(InvalidInput):
            submit_recode(self.store, 'volume', 'request', (2, 2, 5))
        self.assertEqual(self.slots(), before)
        self.assertIsNone(self.receipt())
        self.assertEqual(read_volume(self.store, 'volume').stripes, STRIPES)

    def test_distinct_dependent_rows(self):
        self.make_volume()
        before = self.slots()
        with self.assertRaises(InvalidInput):
            submit_recode(self.store, 'volume', 'request', (1, 2, 3))
        self.reopen()
        with self.assertRaises(UnknownRequest):
            self.request()
        self.assertEqual(self.slots(), before)
        self.assertEqual(read_volume(self.store, 'volume').stripes, STRIPES)

    def test_already_at_target(self):
        self.make_volume()
        before = self.slots()
        receipt = submit_recode(self.store, 'volume', 'request', INITIAL, write_limit=0)
        self.assertIsInstance(receipt, RecodeReceipt)
        self.assertEqual(self.slots(), before)
        self.assertEqual(receipt.generations, (0, 0, 0))

    def test_budgeted_resume(self):
        self.make_volume()
        for _ in range(10):
            result = submit_recode(self.store, 'volume', 'request', TARGET, write_limit=1)
            self.assertEqual(read_volume(self.store, 'volume').stripes, STRIPES)
            if isinstance(result, RecodeReceipt):
                break
            self.assertIsNone(self.receipt())
            self.reopen()
        else:
            self.fail('single-write resumes did not reach the target')
        self.assertEqual(tuple(s.payload for s in self.slots()), FINAL_SLOTS)

    def test_pending_blocks_another_request_for_same_volume(self):
        self.make_volume()
        pending = submit_recode(self.store, 'volume', 'request', TARGET, write_limit=0)
        self.assertIsInstance(pending, RecodeRequest)
        with self.assertRaises(ConflictError):
            submit_recode(self.store, 'volume', 'other', TARGET)
        with self.assertRaises(UnknownRequest):
            self.request('other')
        self.assertIsInstance(submit_recode(self.store, 'volume', 'request', TARGET), RecodeReceipt)

    def test_unbound_physical_generation_is_rejected(self):
        _, volume = self.make_volume()
        compare_and_write_slot(self.store, 'volume', volume.medium_id, 2, 0, b'\x0a')
        with self.assertRaises(EvidenceError):
            read_volume(self.store, 'volume')
        with self.assertRaises(EvidenceError):
            submit_recode(self.store, 'volume', 'request', TARGET)
        with self.assertRaises(UnknownRequest):
            self.request()

    def test_slot_port_rejects_stale_generation(self):
        _, volume = self.make_volume()
        written = compare_and_write_slot(self.store, 'volume', volume.medium_id, 2, 0, b'\x0a')
        before = self.slots()
        self.assertEqual(written.generation, 1)
        with self.assertRaises(ConflictError):
            compare_and_write_slot(self.store, 'volume', volume.medium_id, 2, 0, b'\xff')
        self.assertEqual(self.slots(), before)
