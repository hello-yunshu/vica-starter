"""Canonical serialization (SPEC v0.1 section 5).

Rules:
1. UTF-8
2. JSON
3. object keys sorted lexicographically
4. NaN / Infinity rejected
5. no extra whitespace
6. stable number formatting (floats use repr round-trip)
7. standard JSON string escaping
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(obj: Any) -> bytes:
    """Return the canonical byte representation of *obj*.

    Raises ``ValueError`` if *obj* contains NaN / Infinity (or is otherwise
    not JSON-serializable).
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def stable_hash(obj: Any) -> str:
    """Return a stable hex digest (SHA-256) of the canonical representation.

    Deliberately not ``hash()``: Python's built-in hash is salted per process.
    """
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()