class ArchiveError(Exception):
    """An operation could not fulfill the archive contract."""


class InvalidInput(ArchiveError, ValueError):
    pass


class ConflictError(ArchiveError):
    pass


class UnknownRecording(ArchiveError):
    pass


class RetiredRecording(ArchiveError):
    pass


class UnknownVolume(ArchiveError):
    pass


class UnknownRequest(ArchiveError):
    pass


class EvidenceError(ArchiveError):
    pass


class StorageError(ArchiveError):
    pass


class SlotReplyLost(ArchiveError):
    """The slot port did not return an acknowledgement."""


def require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput(f'{field} must be nonempty text')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise InvalidInput(f'{field} must be valid UTF-8 text') from exc
    return value
