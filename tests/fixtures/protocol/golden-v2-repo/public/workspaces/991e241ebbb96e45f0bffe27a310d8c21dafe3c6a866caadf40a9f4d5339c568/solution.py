"""A tiny KV store with a single-level transaction."""
from __future__ import annotations


def solve(ops: list[tuple[str, Any]]) -> list[str | None]:
    """Run a KV op script; return ``get`` results. (BUG: commit drops writes.)"""
    data: dict[str, str] = {}
    tx: dict[str, str] | None = None
    out: list[str | None] = []
    for op, *args in ops:
        if op == "begin":
            tx = dict(data)
        elif op == "set":
            if tx is not None:
                tx[args[0]] = args[1]
            else:
                data[args[0]] = args[1]
        elif op == "commit":
            if tx is not None:
                tx = None  # BUG: writes are not persisted
        elif op == "rollback":
            tx = None
        elif op == "get":
            src = tx if tx is not None else data
            out.append(src.get(args[0]))
    return out
