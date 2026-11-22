from dataclasses import asdict, dataclass
import json

from errors import EvidenceError, require_text
from recording.channels import ChannelStripe


@dataclass(frozen=True, slots=True)
class ChannelProvenance:
    recording_id: str
    position: int
    channel_id: str
    origin: str


Provenance = tuple[ChannelProvenance, ChannelProvenance, ChannelProvenance]


def order_provenance(recording_id: str, channels: tuple[ChannelStripe, ...]) -> Provenance:
    return tuple(
        ChannelProvenance(
            recording_id, index, channel.channel_id, require_text(channel.origin, 'channel origin')
        )
        for index, channel in enumerate(channels)
    )


def check_provenance(provenance: Provenance, recording_id: str) -> Provenance:
    if len(provenance) != 3:
        raise EvidenceError('three provenance entries are required')
    for index, item in enumerate(provenance):
        if item.recording_id != recording_id or type(item.position) is not int or item.position != index:
            raise EvidenceError('provenance does not match the recording and channel positions')
        try:
            require_text(item.channel_id, 'channel ID')
            require_text(item.origin, 'channel origin')
        except ValueError as exc:
            raise EvidenceError('invalid recorded channel provenance') from exc
    if len({item.channel_id for item in provenance}) != 3:
        raise EvidenceError('provenance repeats a channel identity')
    return provenance


def dump_provenance(provenance: Provenance) -> str:
    return json.dumps([asdict(item) for item in provenance], ensure_ascii=False)


def load_provenance(data: str, recording_id: str) -> Provenance:
    try:
        provenance = tuple(ChannelProvenance(**item) for item in json.loads(data))
    except (TypeError, ValueError) as exc:
        raise EvidenceError('unreadable channel provenance') from exc
    return check_provenance(provenance, recording_id)
