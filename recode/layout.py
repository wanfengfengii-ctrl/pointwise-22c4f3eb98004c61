from collections import deque
from dataclasses import dataclass

from errors import InvalidInput
from volume.basis import Basis, validate_basis


@dataclass(frozen=True, slots=True)
class SlotTransform:
    slot_index: int
    old_row: int
    new_row: int


def _invertible(rows: Basis) -> bool:
    left = list(rows)
    for index in range(3):
        bit = 1 << index
        pivot = next((i for i in range(index, 3) if left[i] & bit), None)
        if pivot is None:
            return False
        left[index], left[pivot] = left[pivot], left[index]
        for other in range(3):
            if other != index and left[other] & bit:
                left[other] ^= left[index]
    return True


def _neighbours(rows: Basis):
    for index in range(3):
        for row in range(1, 8):
            if row == rows[index]:
                continue
            candidate = rows[:index] + (row,) + rows[index + 1:]
            if _invertible(candidate):
                yield candidate, index, row


def plan_slot_changes(current: Basis, target: Basis) -> tuple[SlotTransform, ...]:
    """Plan single-slot row changes that keep every intermediate layout invertible.

    The medium is committed one slot at a time and a reply may be lost after a
    commit.  A naive row-by-row sweep can pass through a singular layout (for
    the sample: (1, 2, 5) -> (2, 2, 5)), after which the original stripes can
    no longer be decoded from the medium alone.  A shortest path over the
    invertible layouts guarantees every pause point remains readable.
    """
    old = validate_basis(current)
    new = validate_basis(target)
    if old == new:
        return ()
    parents: dict[Basis, tuple[Basis, int, int] | None] = {old: None}
    queue = deque([old])
    while queue:
        state = queue.popleft()
        for candidate, index, row in _neighbours(state):
            if candidate in parents:
                continue
            parents[candidate] = (state, index, row)
            if candidate == new:
                steps = []
                node = new
                while parents[node] is not None:
                    previous, changed, new_row = parents[node]
                    steps.append(SlotTransform(changed, previous[changed], new_row))
                    node = previous
                steps.reverse()
                return tuple(steps)
            queue.append(candidate)
    raise InvalidInput('no reversible slot path reaches the target layout')
