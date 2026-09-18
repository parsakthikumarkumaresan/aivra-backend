from __future__ import annotations


def compute_billable_minutes(duration_seconds: int) -> int:
    """Jaan Voice Credit billing-rounding policy (Phase 4 spec section 5).

    Explicit, documented rule (not silently guessed): bill
    ``ceil(duration_seconds / 60)`` minutes, with a 1-minute minimum for
    any call that actually connected — standard telephony billing
    convention. A call that never connected (``duration_seconds == 0``) is
    not billed at all.

    Examples: 2m14s (134s) -> 3 minutes. 10s -> 1 minute. 0s -> 0 minutes.
    """
    if duration_seconds <= 0:
        return 0
    return max(1, -(-duration_seconds // 60))
