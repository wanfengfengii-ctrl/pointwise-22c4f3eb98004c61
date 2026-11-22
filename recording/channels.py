from dataclasses import dataclass

from errors import InvalidInput, require_text


@dataclass(frozen=True, slots=True)
class ChannelStripe:
    channel_id: str
    payload: bytes
    origin: str


def validate_channels(channels) -> tuple[ChannelStripe, ChannelStripe, ChannelStripe]:
    try:
        ordered = tuple(channels)
    except TypeError as exc:
        raise InvalidInput('three ordered channels are required') from exc
    if len(ordered) != 3 or any(not isinstance(channel, ChannelStripe) for channel in ordered):
        raise InvalidInput('three ChannelStripe values are required')
    for channel in ordered:
        require_text(channel.channel_id, 'channel ID')
        if not isinstance(channel.payload, bytes):
            raise InvalidInput('channel payload must be bytes')
    if len({channel.channel_id for channel in ordered}) != 3:
        raise InvalidInput('channel identities must be distinct')
    if len({len(channel.payload) for channel in ordered}) != 1:
        raise InvalidInput('channel payloads must have equal lengths')
    return ordered
