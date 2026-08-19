"""Generic explicit state machine (spec section 40).

Domains define a ``{state: {allowed_next_states}}`` transition table and
wrap it in a ``StateMachine`` instance; call sites call
``assert_transition_allowed`` before mutating a row's status column instead
of comparing strings ad hoc. This lives in shared because it is a pure
algorithm, not a domain — HR and Voice each own their own transition
tables (see app.ai_employees.hr / app.ai_employees.voice), so this does not
violate the HR/Voice isolation rule.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from app.shared.errors.exceptions import InvalidStateTransitionError

StateT = TypeVar("StateT")


class StateMachine(Generic[StateT]):
    def __init__(self, transitions: dict[StateT, frozenset[StateT]]) -> None:
        self._transitions = transitions

    def can_transition(self, current: StateT, target: StateT) -> bool:
        if current == target:
            return True
        return target in self._transitions.get(current, frozenset())

    def assert_transition_allowed(self, current: StateT, target: StateT) -> None:
        if not self.can_transition(current, target):
            raise InvalidStateTransitionError(
                f"Cannot transition from '{current}' to '{target}'.",
                details={"from": str(current), "to": str(target)},
            )
