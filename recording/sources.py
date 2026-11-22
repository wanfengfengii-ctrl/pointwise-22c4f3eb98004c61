from dataclasses import dataclass
import sqlite3

from errors import ConflictError, EvidenceError, RetiredRecording, UnknownRecording
from recording.channels import ChannelStripe, validate_channels
from recording.provenance import ChannelProvenance, Provenance, check_provenance


@dataclass(frozen=True, slots=True)
class SourceRecording:
    recording_id: str
    channels: tuple[ChannelStripe, ChannelStripe, ChannelStripe]
    provenance: Provenance

    @property
    def stripes(self) -> tuple[bytes, bytes, bytes]:
        return tuple(channel.payload for channel in self.channels)


def store_recording(db: sqlite3.Connection, recording: SourceRecording) -> None:
    exists = db.execute(
        'SELECT 1 FROM recordings WHERE recording_id = ?', (recording.recording_id,)
    ).fetchone()
    if exists is not None:
        raise ConflictError(f'recording already exists: {recording.recording_id}')
    db.execute(
        'INSERT INTO recordings(recording_id, stripe_length) VALUES (?, ?)',
        (recording.recording_id, len(recording.channels[0].payload)),
    )
    db.executemany(
        '''INSERT INTO source_channels(recording_id, position, channel_id, origin, payload)
           VALUES (?, ?, ?, ?, ?)''',
        [
            (recording.recording_id, origin.position, origin.channel_id, origin.origin, channel.payload)
            for origin, channel in zip(recording.provenance, recording.channels, strict=True)
        ],
    )


def _recording_row(db: sqlite3.Connection, recording_id: str) -> sqlite3.Row:
    row = db.execute(
        'SELECT stripe_length, retired_volume FROM recordings WHERE recording_id = ?', (recording_id,)
    ).fetchone()
    if row is None:
        raise UnknownRecording(f'unknown recording: {recording_id}')
    return row


def _channel_rows(db: sqlite3.Connection, recording_id: str):
    return db.execute(
        '''SELECT position, channel_id, origin, payload FROM source_channels
           WHERE recording_id = ? ORDER BY position''',
        (recording_id,),
    ).fetchall()


def _provenance(recording_id: str, rows) -> Provenance:
    ordered = tuple(
        ChannelProvenance(recording_id, row['position'], row['channel_id'], row['origin'])
        for row in rows
    )
    return check_provenance(ordered, recording_id)


def load_readable_recording(db: sqlite3.Connection, recording_id: str) -> SourceRecording:
    record = _recording_row(db, recording_id)
    if record['retired_volume'] is not None:
        raise RetiredRecording(f'recording already retired: {recording_id}')
    rows = _channel_rows(db, recording_id)
    provenance = _provenance(recording_id, rows)
    try:
        channels = validate_channels(
            ChannelStripe(row['channel_id'], row['payload'], row['origin']) for row in rows
        )
    except ValueError as exc:
        raise EvidenceError('stored recording has invalid channels') from exc
    if len(channels[0].payload) != record['stripe_length']:
        raise EvidenceError('stored recording has an unexpected stripe length')
    return SourceRecording(recording_id, channels, provenance)


def load_recording_provenance(db: sqlite3.Connection, recording_id: str) -> Provenance:
    _recording_row(db, recording_id)
    return _provenance(recording_id, _channel_rows(db, recording_id))


def commit_retirement(db: sqlite3.Connection, recording_id: str, volume_id: str) -> None:
    updated = db.execute(
        '''UPDATE recordings SET retired_volume = ?
           WHERE recording_id = ? AND retired_volume IS NULL''',
        (volume_id, recording_id),
    )
    if updated.rowcount != 1:
        raise ConflictError('recording is no longer eligible for retirement')
    cleared = db.execute(
        'UPDATE source_channels SET payload = NULL WHERE recording_id = ? AND payload IS NOT NULL',
        (recording_id,),
    )
    if cleared.rowcount != 3:
        raise EvidenceError('retirement could not release three source stripes')
