from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from inspection.register import list_shift_entries
from recode.receipts import load_first_receipt
from recode.requests import get_request
from recording.channels import ChannelStripe
from recording.ingest import accept_recording
from recording.retirement import retire_recording
from storage import ArchiveStore
from volume.catalog import get_verified_volume
from volume.seal import seal_volume
from volume.slots import read_slots


STRIPES = (bytes([7]), bytes([11]), bytes([13]))
INITIAL = (1, 2, 5)
TARGET = (2, 4, 3)
FINAL_SLOTS = (bytes([11]), bytes([13]), bytes([12]))
NAMES = ('Z', 'X', 'Y')
ORIGINS = ('rig-42/lateral', 'rig-42/axial', 'rig-42/vertical')


def channels_for(stripes=STRIPES):
    return tuple(ChannelStripe(name, data, origin) for name, data, origin in zip(NAMES, stripes, ORIGINS, strict=True))


class ArchiveCase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = ArchiveStore(self.root)

    def reopen(self):
        self.store = ArchiveStore(self.root)

    def make_volume(self, *, recording_id='recording', volume_id='volume', stripes=STRIPES, retire=True):
        source = accept_recording(self.store, recording_id, channels_for(stripes))
        volume = seal_volume(self.store, recording_id, volume_id, INITIAL)
        if retire:
            retire_recording(self.store, recording_id, volume_id)
        return source, volume

    def slots(self, volume_id='volume'):
        with self.store.catalog() as db:
            volume = get_verified_volume(db, volume_id)
        return read_slots(self.store, volume.volume_id, volume.medium_id)

    def receipt(self, request_id='request'):
        with self.store.catalog() as db:
            return load_first_receipt(db, request_id)

    def request(self, request_id='request'):
        with self.store.catalog() as db:
            return get_request(db, request_id)

    def shifts(self):
        with self.store.catalog() as db:
            return list_shift_entries(db)
