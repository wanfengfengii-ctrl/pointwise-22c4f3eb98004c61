from dataclasses import dataclass

from volume.basis import Basis, validate_basis


@dataclass(frozen=True, slots=True)
class SlotTransform:
    slot_index: int
    old_row: int
    new_row: int


def plan_slot_changes(current: Basis, target: Basis) -> tuple[SlotTransform, ...]:
    old = validate_basis(current)
    new = validate_basis(target)
    return tuple(
        SlotTransform(index, before, after)
        for index, (before, after) in enumerate(zip(old, new, strict=True))
        if before != after
    )
