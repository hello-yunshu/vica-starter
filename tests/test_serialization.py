"""Tests for canonical serialization (SPEC v0.1 section 5)."""

from __future__ import annotations

import pytest

from vica.protocol.serialization import canonical_json_bytes, stable_hash


class TestCanonicalSerialization:
    def test_key_order_ignored(self) -> None:
        a = canonical_json_bytes({"b": 1, "a": 2})
        b = canonical_json_bytes({"a": 2, "b": 1})
        assert a == b

    def test_nested_keys_sorted_recursively(self) -> None:
        a = canonical_json_bytes({"x": {"z": 1, "y": {"m": 0, "l": 1}}})
        b = canonical_json_bytes({"x": {"y": {"l": 1, "m": 0}, "z": 1}})
        assert a == b == b'{"x":{"y":{"l":1,"m":0},"z":1}}'

    def test_no_whitespace_and_unicode(self) -> None:
        assert canonical_json_bytes({"a": "中文", "b": 1}) == '{"a":"中文","b":1}'.encode()

    def test_ascii_not_escaped(self) -> None:
        # ensure_ascii=False: non-ASCII preserved as UTF-8 bytes
        data = canonical_json_bytes({"name": "café"})
        assert data == '{"name":"café"}'.encode()

    def test_stdout_escape_rules(self) -> None:
        data = canonical_json_bytes({"s": 'a"b\\c\nd'})
        assert json_loads(data) == {"s": 'a"b\\c\nd'}

    def test_nan_rejected(self) -> None:
        with pytest.raises(ValueError):
            canonical_json_bytes({"x": float("nan")})

    def test_infinity_rejected(self) -> None:
        with pytest.raises(ValueError):
            canonical_json_bytes({"x": float("inf")})

    @pytest.mark.parametrize(
        "obj",
        [
            {"a": 1},
            [1, 2, 3],
            {"nested": {"deep": [{"a": None}]}},
            {"t": True, "f": False, "n": None},
            3.14159,
        ],
    )
    def test_round_trip(self, obj: object) -> None:
        assert json_loads(canonical_json_bytes(obj)) == obj

    def test_stable_hash_string(self) -> None:
        assert stable_hash({"a": 1}) == stable_hash({"a": 1})
        assert stable_hash({"a": 1}) != stable_hash({"a": 2})
        assert len(stable_hash({})) == 64

    def test_stable_hash_cross_order(self) -> None:
        assert stable_hash({"b": 1, "a": 2}) == stable_hash({"a": 2, "b": 1})


def json_loads(data: bytes):
    import json

    return json.loads(data.decode("utf-8"))