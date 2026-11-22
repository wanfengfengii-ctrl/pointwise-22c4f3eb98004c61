from contextlib import contextmanager
from pathlib import Path
import sqlite3

from errors import StorageError


_CATALOG = '''
CREATE TABLE IF NOT EXISTS recordings (
    recording_id TEXT PRIMARY KEY,
    stripe_length INTEGER NOT NULL CHECK (stripe_length >= 0),
    retired_volume TEXT
);
CREATE TABLE IF NOT EXISTS source_channels (
    recording_id TEXT NOT NULL REFERENCES recordings(recording_id),
    position INTEGER NOT NULL CHECK (position BETWEEN 0 AND 2),
    channel_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    payload BLOB,
    PRIMARY KEY (recording_id, position),
    UNIQUE (recording_id, channel_id)
);
CREATE TABLE IF NOT EXISTS volumes (
    volume_id TEXT PRIMARY KEY,
    medium_id TEXT NOT NULL UNIQUE,
    recording_id TEXT NOT NULL REFERENCES recordings(recording_id),
    stripe_length INTEGER NOT NULL CHECK (stripe_length >= 0),
    initial_basis TEXT NOT NULL,
    initial_generations TEXT NOT NULL,
    provenance TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recode_requests (
    request_id TEXT PRIMARY KEY,
    volume_id TEXT NOT NULL REFERENCES volumes(volume_id),
    target TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'done'))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_request
    ON recode_requests(volume_id) WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS slot_write_intents (
    request_id TEXT NOT NULL REFERENCES recode_requests(request_id),
    volume_id TEXT NOT NULL REFERENCES volumes(volume_id),
    slot_index INTEGER NOT NULL CHECK (slot_index BETWEEN 0 AND 2),
    old_generation INTEGER NOT NULL CHECK (old_generation >= 0),
    new_generation INTEGER NOT NULL CHECK (new_generation = old_generation + 1),
    old_row INTEGER NOT NULL CHECK (old_row BETWEEN 1 AND 7),
    new_row INTEGER NOT NULL CHECK (new_row BETWEEN 1 AND 7 AND new_row <> old_row),
    confirmed INTEGER NOT NULL DEFAULT 0 CHECK (confirmed IN (0, 1)),
    PRIMARY KEY (volume_id, slot_index, new_generation)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_unconfirmed_write
    ON slot_write_intents(volume_id) WHERE confirmed = 0;
CREATE TABLE IF NOT EXISTS recode_receipts (
    request_id TEXT PRIMARY KEY REFERENCES recode_requests(request_id),
    receipt_id TEXT NOT NULL UNIQUE,
    volume_id TEXT NOT NULL REFERENCES volumes(volume_id),
    issued_at TEXT NOT NULL,
    target TEXT NOT NULL,
    generations TEXT NOT NULL,
    checksums TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shift_entries (
    entry_id INTEGER PRIMARY KEY,
    shift_id TEXT NOT NULL,
    volume_id TEXT NOT NULL REFERENCES volumes(volume_id),
    recording_id TEXT NOT NULL REFERENCES recordings(recording_id),
    provenance TEXT NOT NULL,
    stripe_digests TEXT NOT NULL,
    basis TEXT NOT NULL,
    generations TEXT NOT NULL,
    request_id TEXT REFERENCES recode_requests(request_id),
    status TEXT NOT NULL CHECK (status IN ('available', 'pending', 'done')),
    receipt_id TEXT REFERENCES recode_receipts(receipt_id),
    CHECK ((status = 'available') = (request_id IS NULL)),
    CHECK ((status = 'done') = (receipt_id IS NOT NULL))
);
'''

_MEDIA = '''
CREATE TABLE IF NOT EXISTS slots (
    medium_id TEXT NOT NULL,
    volume_id TEXT NOT NULL,
    slot_index INTEGER NOT NULL CHECK (slot_index BETWEEN 0 AND 2),
    generation INTEGER NOT NULL CHECK (generation >= 0),
    payload BLOB NOT NULL,
    checksum TEXT NOT NULL,
    PRIMARY KEY (medium_id, slot_index)
);
CREATE INDEX IF NOT EXISTS slots_by_volume ON slots(volume_id);
'''


class ArchiveStore:
    """Open the local directory and the separately committed slot medium."""

    def __init__(self, root: str | Path):
        self.root = Path(root).absolute()
        self.catalog_path = self.root / 'catalog.sqlite3'
        self.media_path = self.root / 'medium.sqlite3'
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError('cannot open archive directory') from exc
        self._initialize(self.catalog_path, _CATALOG)
        self._initialize(self.media_path, _MEDIA)

    @staticmethod
    @contextmanager
    def _connection(path: Path, *, create: bool = False):
        db = None
        try:
            mode = 'rwc' if create else 'rw'
            db = sqlite3.connect(
                f'{path.as_uri()}?mode={mode}', uri=True, isolation_level=None, timeout=5
            )
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys = ON')
            db.execute('PRAGMA secure_delete = ON')
            yield db
        except sqlite3.Error as exc:
            raise StorageError(f'{path.name} operation failed: {exc}') from exc
        finally:
            if db is not None:
                db.close()

    def _initialize(self, path: Path, schema: str) -> None:
        with self._connection(path, create=True) as db:
            db.executescript('BEGIN IMMEDIATE;\n' + schema + '\nCOMMIT;')

    @contextmanager
    def _transaction(self, path: Path, write: bool):
        with self._connection(path) as db:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            db.commit()

    def catalog(self, *, write: bool = False):
        return self._transaction(self.catalog_path, write)

    def media(self, *, write: bool = False):
        return self._transaction(self.media_path, write)
