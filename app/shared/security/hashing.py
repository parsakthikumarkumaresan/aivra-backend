"""Fast, deterministic hashing for high-entropy secrets (refresh tokens,
API keys) that must be looked up by equality in the database.

Unlike passwords (low entropy, need slow adaptive hashing — see
``passwords.py``), a 48-byte random token already resists brute force, so a
plain SHA-256 digest is sufficient and allows an indexed equality lookup.
"""

from __future__ import annotations

import hashlib


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
