from errors import ConflictError, EvidenceError, InvalidInput, RetiredRecording, StorageError, UnknownRecording, UnknownVolume
from inspection.shifts import reconcile_shift
from pickup.read import read_volume
from recording.channels import ChannelStripe
from recording.ingest import accept_recording
from recording.retirement import retire_recording
from recording.sources import load_readable_recording, load_recording_provenance
from tests.support import ArchiveCase, INITIAL, NAMES, ORIGINS, STRIPES, channels_for
from volume.seal import seal_volume


class RecordingTests(ArchiveCase):
    def test_seal_and_retire(self):
        source = accept_recording(self.store, 'recording', channels_for())
        seal_volume(self.store, 'recording', 'volume', INITIAL)
        self.assertEqual(tuple(s.payload for s in self.slots()), (b'\x07', b'\x0b', b'\x0a'))
        self.assertEqual(read_volume(self.store, 'volume').stripes, STRIPES)
        self.assertEqual(retire_recording(self.store, 'recording', 'volume'), source.provenance)
        with self.store.catalog() as db:
            with self.assertRaises(RetiredRecording):
                load_readable_recording(db, 'recording')
            self.assertEqual(load_recording_provenance(db, 'recording'), source.provenance)
            payloads = db.execute('SELECT payload FROM source_channels ORDER BY position').fetchall()
            self.assertEqual([row['payload'] for row in payloads], [None, None, None])
        pickup = read_volume(self.store, 'volume')
        self.assertEqual(pickup.stripes, STRIPES)
        self.assertEqual(pickup.provenance, source.provenance)
        shift = reconcile_shift(self.store, 'handoff', 'volume')
        self.assertEqual(shift.observation.pickup, pickup)
        self.assertEqual(shift.entry.status, 'available')

    def test_explicit_empty(self):
        self.make_volume(stripes=(b'', b'', b''))
        self.reopen()
        self.assertEqual(read_volume(self.store, 'volume').stripes, (b'', b'', b''))
        self.assertEqual(tuple(s.payload for s in self.slots()), (b'', b'', b''))

    def test_provenance_order(self):
        self.make_volume()
        self.reopen()
        pickup = read_volume(self.store, 'volume')
        self.assertEqual(
            [(p.position, p.channel_id, p.origin, data[0]) for p, data in zip(pickup.provenance, pickup.stripes, strict=True)],
            [(0, 'Z', ORIGINS[0], 7), (1, 'X', ORIGINS[1], 11), (2, 'Y', ORIGINS[2], 13)],
        )
        self.assertEqual(tuple(p.channel_id for p in pickup.provenance), NAMES)

    def test_multi_byte(self):
        stripes = (bytes([7, 250]), bytes([11, 1]), bytes([13, 128]))
        accept_recording(self.store, 'recording', channels_for(stripes))
        seal_volume(self.store, 'recording', 'volume', (2, 4, 3))
        retire_recording(self.store, 'recording', 'volume')
        self.assertEqual(tuple(s.payload for s in self.slots()), (bytes([11, 1]), bytes([13, 128]), bytes([12, 251])))
        self.assertEqual(read_volume(self.store, 'volume').stripes, stripes)

    def test_unpublished_seal(self):
        accept_recording(self.store, 'recording', channels_for())

        def damage_staged_slot(medium_id):
            with self.store.media(write=True) as db:
                row = db.execute('SELECT payload FROM slots WHERE medium_id = ? AND slot_index = 2', (medium_id,)).fetchone()
                self.assertEqual(row['payload'], b'\x0a')
                db.execute('UPDATE slots SET payload = ? WHERE medium_id = ? AND slot_index = 2', (b'\xff', medium_id))

        with self.assertRaises(EvidenceError):
            seal_volume(self.store, 'recording', 'volume', INITIAL, after_slots=damage_staged_slot)
        self.reopen()
        with self.assertRaises(UnknownVolume):
            read_volume(self.store, 'volume')
        with self.store.media() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM slots').fetchone()[0], 0)
        seal_volume(self.store, 'recording', 'volume', INITIAL)
        self.assertEqual(read_volume(self.store, 'volume').stripes, STRIPES)

    def test_bad_slot(self):
        _, volume = self.make_volume()
        with self.store.media(write=True) as db:
            db.execute('UPDATE slots SET payload = ? WHERE medium_id = ? AND slot_index = 1', (b'\xff', volume.medium_id))
        with self.assertRaises(EvidenceError):
            read_volume(self.store, 'volume')
        with self.assertRaises(EvidenceError):
            reconcile_shift(self.store, 'bad-slot', 'volume')
        self.assertEqual(self.shifts(), ())

    def test_missing_medium(self):
        self.make_volume()
        self.store.media_path.unlink()
        with self.assertRaises(StorageError):
            read_volume(self.store, 'volume')
        self.reopen()
        with self.assertRaises(EvidenceError):
            read_volume(self.store, 'volume')

    def test_restart_preserves_existing(self):
        source, volume = self.make_volume()
        entry = reconcile_shift(self.store, 'before-restart', 'volume').entry
        slots = self.slots()
        self.reopen()
        self.reopen()
        with self.store.catalog() as db:
            with self.assertRaises(RetiredRecording):
                load_readable_recording(db, 'recording')
            self.assertEqual(load_recording_provenance(db, 'recording'), source.provenance)
        self.assertEqual(read_volume(self.store, volume.volume_id).stripes, STRIPES)
        self.assertEqual(self.slots(), slots)
        self.assertEqual(self.shifts(), (entry,))

    def test_unequal_channels(self):
        with self.assertRaises(InvalidInput):
            accept_recording(self.store, 'recording', channels_for((b'a', b'b', b'cc')))
        with self.assertRaises(UnknownRecording):
            seal_volume(self.store, 'recording', 'volume', INITIAL)
        with self.assertRaises(UnknownVolume):
            read_volume(self.store, 'volume')

    def test_atomic_rejection(self):
        with self.assertRaises(InvalidInput):
            accept_recording(self.store, 'recording', channels_for((b'a', b'b', b'cc')))
        self.reopen()
        with self.store.catalog() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM recordings').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM source_channels').fetchone()[0], 0)
        accept_recording(self.store, 'recording', channels_for())
        with self.assertRaises(ConflictError):
            accept_recording(self.store, 'recording', channels_for((b'a', b'b', b'c')))
        seal_volume(self.store, 'recording', 'volume', INITIAL)
        self.assertEqual(read_volume(self.store, 'volume').stripes, STRIPES)

    def test_missing_repeated_or_invalid_channel(self):
        original = channels_for()
        cases = (
            original[:2], (original[0], original[0], original[2]),
            (ChannelStripe('Z', None, 'rig'), *original[1:]),
            (ChannelStripe('Z', b'\x07', ''), *original[1:]),
        )
        for channels in cases:
            with self.subTest(channels=channels), self.assertRaises(InvalidInput):
                accept_recording(self.store, 'recording', channels)
        self.make_volume()
        self.assertEqual(read_volume(self.store, 'volume').stripes, STRIPES)

    def test_retirement_requires_verified_volume(self):
        accept_recording(self.store, 'recording', channels_for())
        with self.assertRaises(UnknownVolume):
            retire_recording(self.store, 'recording', 'volume')
        with self.store.catalog() as db:
            self.assertEqual(load_readable_recording(db, 'recording').stripes, STRIPES)

    def test_foreign_verified_volume(self):
        accept_recording(self.store, 'recording', channels_for())
        self.make_volume(recording_id='foreign', volume_id='foreign-volume', stripes=(b'a', b'b', b'c'))
        with self.assertRaises(ConflictError):
            retire_recording(self.store, 'recording', 'foreign-volume')
        self.reopen()
        with self.store.catalog() as db:
            self.assertEqual(load_readable_recording(db, 'recording').stripes, STRIPES)
        seal_volume(self.store, 'recording', 'volume', INITIAL)
        self.assertEqual(read_volume(self.store, 'volume').stripes, STRIPES)

    def test_retirement_rechecks_medium(self):
        _, volume = self.make_volume(retire=False)
        with self.store.media(write=True) as db:
            db.execute('DELETE FROM slots WHERE medium_id = ? AND slot_index = 0', (volume.medium_id,))
        with self.assertRaises(EvidenceError):
            retire_recording(self.store, 'recording', 'volume')
        with self.store.catalog() as db:
            self.assertEqual(load_readable_recording(db, 'recording').stripes, STRIPES)
