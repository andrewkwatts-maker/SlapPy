"""Tests for the shared input-validation helpers in
:mod:`slappyengine._validation`.

These cover each public canonical validator with both positive and
negative cases, including the standardisations applied during the
consolidation (bool rejection, bytes refusal, numpy scalar acceptance).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from slappyengine._validation import (
    validate_bool,
    validate_callable,
    validate_callback,
    validate_existing_file_path,
    validate_finite_2tuple,
    validate_finite_float,
    validate_finite_or_none,
    validate_int,
    validate_non_empty_str,
    validate_non_negative_float,
    validate_non_negative_int,
    validate_optional_path_like,
    validate_optional_str,
    validate_path_like,
    validate_pathlike,
    validate_positive_finite_or_none,
    validate_positive_float,
    validate_positive_int,
    validate_positive_size_2tuple,
    validate_str,
    validate_unit_float,
    validate_unit_interval,
)


# ---------------------------------------------------------------------------
# String validators
# ---------------------------------------------------------------------------


def test_validate_str_accepts_str():
    assert validate_str("name", "fn", "hello") == "hello"


def test_validate_str_accepts_empty_by_default():
    assert validate_str("name", "fn", "") == ""


def test_validate_str_rejects_empty_when_disallowed():
    with pytest.raises(ValueError, match="non-empty"):
        validate_str("name", "fn", "", allow_empty=False)


def test_validate_str_rejects_bytes():
    with pytest.raises(TypeError, match="must be a str"):
        validate_str("name", "fn", b"hello")


def test_validate_str_rejects_bytearray():
    with pytest.raises(TypeError, match="must be a str"):
        validate_str("name", "fn", bytearray(b"hello"))


def test_validate_str_rejects_none():
    with pytest.raises(TypeError, match="must be a str"):
        validate_str("name", "fn", None)


def test_validate_non_empty_str_rejects_empty():
    with pytest.raises(ValueError, match="non-empty"):
        validate_non_empty_str("name", "fn", "")


def test_validate_optional_str_accepts_none():
    assert validate_optional_str("name", "fn", None) is None


def test_validate_optional_str_rejects_int():
    with pytest.raises(TypeError, match="must be a str"):
        validate_optional_str("name", "fn", 42)


# ---------------------------------------------------------------------------
# Bool validator
# ---------------------------------------------------------------------------


def test_validate_bool_accepts_true():
    assert validate_bool("name", "fn", True) is True


def test_validate_bool_accepts_false():
    assert validate_bool("name", "fn", False) is False


def test_validate_bool_rejects_truthy_int():
    with pytest.raises(TypeError, match="must be a bool"):
        validate_bool("name", "fn", 1)


def test_validate_bool_rejects_none():
    with pytest.raises(TypeError, match="must be a bool"):
        validate_bool("name", "fn", None)


# ---------------------------------------------------------------------------
# Int validators
# ---------------------------------------------------------------------------


def test_validate_int_accepts_plain_int():
    assert validate_int("name", "fn", 7) == 7


def test_validate_int_rejects_bool():
    with pytest.raises(TypeError, match="must be an int"):
        validate_int("name", "fn", True)


def test_validate_int_rejects_float():
    with pytest.raises(TypeError, match="must be an int"):
        validate_int("name", "fn", 3.0)


def test_validate_int_accepts_numpy_int():
    assert validate_int("name", "fn", np.int32(42)) == 42


def test_validate_positive_int_accepts_one():
    assert validate_positive_int("name", "fn", 1) == 1


def test_validate_positive_int_rejects_zero():
    with pytest.raises(ValueError, match=">= 1"):
        validate_positive_int("name", "fn", 0)


def test_validate_positive_int_rejects_negative():
    with pytest.raises(ValueError, match=">= 1"):
        validate_positive_int("name", "fn", -3)


def test_validate_positive_int_rejects_bool_true():
    # Standardisation: bool must be refused so True can't silently mean 1.
    with pytest.raises(TypeError, match="must be an int"):
        validate_positive_int("name", "fn", True)


def test_validate_positive_int_respects_maximum():
    assert validate_positive_int("name", "fn", 5, maximum=10) == 5
    with pytest.raises(ValueError, match="<= 10"):
        validate_positive_int("name", "fn", 11, maximum=10)


def test_validate_non_negative_int_accepts_zero():
    assert validate_non_negative_int("name", "fn", 0) == 0


def test_validate_non_negative_int_rejects_bool():
    # Standardisation: topology previously accepted bool silently (True -> 1).
    # The shared validator now rejects bool — this is the canonical behaviour.
    with pytest.raises(TypeError, match="must be an int"):
        validate_non_negative_int("name", "fn", True)


def test_validate_non_negative_int_rejects_negative():
    with pytest.raises(ValueError, match=">= 0"):
        validate_non_negative_int("name", "fn", -1)


# ---------------------------------------------------------------------------
# Float validators
# ---------------------------------------------------------------------------


def test_validate_finite_float_accepts_int():
    assert validate_finite_float("name", "fn", 3) == 3.0


def test_validate_finite_float_accepts_float():
    assert validate_finite_float("name", "fn", 2.5) == 2.5


def test_validate_finite_float_accepts_numpy_float():
    assert validate_finite_float("name", "fn", np.float64(1.5)) == 1.5


def test_validate_finite_float_rejects_nan():
    with pytest.raises(ValueError, match="finite"):
        validate_finite_float("name", "fn", float("nan"))


def test_validate_finite_float_rejects_inf():
    with pytest.raises(ValueError, match="finite"):
        validate_finite_float("name", "fn", float("inf"))


def test_validate_finite_float_rejects_bool():
    with pytest.raises(TypeError, match="real number"):
        validate_finite_float("name", "fn", True)


def test_validate_finite_float_rejects_str():
    with pytest.raises(TypeError, match="real number"):
        validate_finite_float("name", "fn", "1.5")


def test_validate_positive_float_rejects_zero():
    with pytest.raises(ValueError, match="> 0"):
        validate_positive_float("name", "fn", 0.0)


def test_validate_positive_float_accepts_small_positive():
    assert validate_positive_float("name", "fn", 1e-9) == 1e-9


def test_validate_non_negative_float_accepts_zero():
    assert validate_non_negative_float("name", "fn", 0.0) == 0.0


def test_validate_non_negative_float_rejects_negative():
    with pytest.raises(ValueError, match=">= 0"):
        validate_non_negative_float("name", "fn", -0.5)


def test_validate_unit_float_accepts_boundaries():
    assert validate_unit_float("name", "fn", 0.0) == 0.0
    assert validate_unit_float("name", "fn", 1.0) == 1.0


def test_validate_unit_float_rejects_above_one():
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        validate_unit_float("name", "fn", 1.5)


def test_validate_unit_interval_is_alias():
    # validate_unit_interval is provided as an alias of validate_unit_float
    # for the post_process module's historical naming.
    assert validate_unit_interval is validate_unit_float


def test_validate_finite_or_none_accepts_none():
    assert validate_finite_or_none("name", "fn", None) is None


def test_validate_finite_or_none_accepts_finite():
    assert validate_finite_or_none("name", "fn", 2.0) == 2.0


def test_validate_positive_finite_or_none_accepts_none():
    assert validate_positive_finite_or_none("name", "fn", None) is None


def test_validate_positive_finite_or_none_rejects_zero():
    with pytest.raises(ValueError, match="> 0"):
        validate_positive_finite_or_none("name", "fn", 0.0)


# ---------------------------------------------------------------------------
# 2-tuple validators
# ---------------------------------------------------------------------------


def test_validate_finite_2tuple_accepts_list():
    assert validate_finite_2tuple("name", "fn", [1.0, 2.0]) == (1.0, 2.0)


def test_validate_finite_2tuple_accepts_tuple():
    assert validate_finite_2tuple("name", "fn", (3, 4)) == (3.0, 4.0)


def test_validate_finite_2tuple_rejects_length_3():
    with pytest.raises(ValueError, match="length 2"):
        validate_finite_2tuple("name", "fn", (1.0, 2.0, 3.0))


def test_validate_finite_2tuple_rejects_str():
    with pytest.raises(TypeError, match="2-tuple"):
        validate_finite_2tuple("name", "fn", "xy")


def test_validate_finite_2tuple_rejects_nan_element():
    with pytest.raises(ValueError, match="finite"):
        validate_finite_2tuple("name", "fn", (1.0, float("nan")))


def test_validate_finite_2tuple_rejects_bool_element():
    with pytest.raises(TypeError, match="real number"):
        validate_finite_2tuple("name", "fn", (True, 1.0))


def test_validate_positive_size_2tuple_accepts():
    assert validate_positive_size_2tuple("name", "fn", (64, 128)) == (64, 128)


def test_validate_positive_size_2tuple_rejects_zero():
    with pytest.raises(ValueError, match=">= 1"):
        validate_positive_size_2tuple("name", "fn", (0, 64))


def test_validate_positive_size_2tuple_rejects_float():
    with pytest.raises(TypeError, match="must be an int"):
        validate_positive_size_2tuple("name", "fn", (64.0, 64))


# ---------------------------------------------------------------------------
# Callable validators
# ---------------------------------------------------------------------------


def test_validate_callable_accepts_function():
    f = lambda: None  # noqa: E731
    assert validate_callable("name", "fn", f) is f


def test_validate_callable_rejects_int():
    with pytest.raises(TypeError, match="callable"):
        validate_callable("name", "fn", 1)


def test_validate_callback_is_alias():
    assert validate_callback is validate_callable


# ---------------------------------------------------------------------------
# Path validators
# ---------------------------------------------------------------------------


def test_validate_path_like_accepts_str():
    assert validate_path_like("name", "fn", "some/path") == Path("some/path")


def test_validate_path_like_accepts_path():
    p = Path("some/path")
    assert validate_path_like("name", "fn", p) == p


def test_validate_path_like_rejects_empty_str():
    with pytest.raises(ValueError, match="empty"):
        validate_path_like("name", "fn", "")


def test_validate_path_like_rejects_bool():
    with pytest.raises(TypeError, match="str or pathlib.Path"):
        validate_path_like("name", "fn", True)


def test_validate_path_like_rejects_int():
    with pytest.raises(TypeError, match="str or pathlib.Path"):
        validate_path_like("name", "fn", 42)


def test_validate_pathlike_is_alias():
    assert validate_pathlike is validate_path_like


def test_validate_optional_path_like_accepts_none():
    assert validate_optional_path_like("name", "fn", None) is None


def test_validate_optional_path_like_accepts_str():
    assert validate_optional_path_like("name", "fn", "x") == Path("x")


def test_validate_existing_file_path_accepts_file(tmp_path):
    f = tmp_path / "hi.txt"
    f.write_text("ok")
    assert validate_existing_file_path("name", "fn", str(f)) == f


def test_validate_existing_file_path_rejects_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        validate_existing_file_path("name", "fn", str(tmp_path / "missing"))


def test_validate_existing_file_path_rejects_directory(tmp_path):
    with pytest.raises(FileNotFoundError, match="not a regular file"):
        validate_existing_file_path("name", "fn", str(tmp_path))
