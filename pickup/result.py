from dataclasses import dataclass

from errors import EvidenceError
from recording.provenance import Provenance, check_provenance
from volume.basis import Stripes
from volume.catalog import VolumeRecord


@dataclass(frozen=True, slots=True)
class PickupResult:
    volume_id: str
    recording_id: str
    stripes: Stripes
    provenance: Provenance


def make_pickup_result(volume: VolumeRecord, stripes: Stripes) -> PickupResult:
    provenance = check_provenance(volume.provenance, volume.recording_id)
    if len(stripes) != 3 or any(len(stripe) != volume.stripe_length for stripe in stripes):
        raise EvidenceError('decoded stripes do not match the volume seal')
    return PickupResult(volume.volume_id, volume.recording_id, stripes, provenance)
