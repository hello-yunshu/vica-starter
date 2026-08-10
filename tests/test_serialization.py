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

    # --- Golden vectors -----------------------------------------------------
    # Hardcoded SHA-256 digests lock the canonical byte encoding so that a
    # future change to the serializer (byte layout, float formatting, escaping)
    # is caught. These are frozen Protocol v0.1 values, not derived at runtime.
    @pytest.mark.parametrize(
        ("obj", "hexdigest"),
        [
            ({}, "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"),
            ({"a": 1}, "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"),
            (
                {"name": "中文", "x": 2},
                "0a3a0c50bb16d640443efe4ebca47fa5efe9cc94c8e5da1600ce92e2e08a8ae8",
            ),
            (
                {"z": [1, {"b": 2, "a": 3}], "k": "v"},
                "970cb3249ca4910b28e1a72e97075daedffea175ba8cf79febf16c188df6b455",
            ),
        ],
    )
    def test_golden_sha256_vectors(self, obj: object, hexdigest: str) -> None:
        assert stable_hash(obj) == hexdigest

    @pytest.mark.parametrize(
        ("obj", "canonical"),
        [
            ({}, b"{}"),
            ({"a": 1}, b'{"a":1}'),
            ({"name": "中文", "x": 2}, b'{"name":"\xe4\xb8\xad\xe6\x96\x87","x":2}'),
            ({"z": [1, {"b": 2, "a": 3}], "k": "v"}, b'{"k":"v","z":[1,{"a":3,"b":2}]}'),
        ],
    )
    def test_golden_canonical_bytes(self, obj: object, canonical: bytes) -> None:
        assert canonical_json_bytes(obj) == canonical


def json_loads(data: bytes):
    import json

    return json.loads(data.decode("utf-8"))