"""Самопроверка эталонной модели и утилит образа памяти."""
import numpy as np
import pytest

from model.gemm_ref import from_hex_lines, gemm_ref, gemm_ref_naive, to_hex_lines


@pytest.mark.parametrize("m,n,k", [(1, 1, 1), (3, 5, 7), (8, 8, 8), (13, 2, 31)])
def test_ref_matches_naive(m, n, k):
    rng = np.random.default_rng(m * 100 + n * 10 + k)
    a = rng.integers(-128, 128, (m, k), dtype=np.int8)
    b = rng.integers(-128, 128, (k, n), dtype=np.int8)
    assert np.array_equal(gemm_ref(a, b), gemm_ref_naive(a, b))


def test_ref_extremes():
    a = np.full((2, 64), -128, dtype=np.int8)
    b = np.full((64, 3), -128, dtype=np.int8)
    assert np.all(gemm_ref(a, b) == 64 * 16384)
    b[:, 1] = 127
    assert np.all(gemm_ref(a, b)[:, 1] == 64 * -128 * 127)


def test_ref_wraps_like_int32():
    # 140000 * 16384 > 2^31: накопление должно переполниться по модулю 2^32, как в int32
    k = 140_000
    a = np.full((1, k), -128, dtype=np.int8)
    b = np.full((k, 1), -128, dtype=np.int8)
    exact = k * 16384
    wrapped = (exact + 2**31) % 2**32 - 2**31
    assert gemm_ref(a, b)[0, 0] == wrapped
    assert gemm_ref_naive(a[:, :2000], b[:2000]).item() == 2000 * 16384


def test_ref_rejects_wrong_dtype():
    with pytest.raises(TypeError):
        gemm_ref(np.zeros((2, 2), np.int16), np.zeros((2, 2), np.int8))


@pytest.mark.parametrize("bus", [4, 16])
def test_hex_roundtrip(bus):
    data = bytes(range(256)) * 2
    lines = to_hex_lines(data, bus)
    assert lines[0].endswith(f"{0:02x}") and lines[0].startswith(f"{bus - 1:02x}")
    assert from_hex_lines(lines + ["// comment", "@10"], bus) == data
    with pytest.raises(ValueError):
        from_hex_lines(["x" * (2 * bus)], bus)
