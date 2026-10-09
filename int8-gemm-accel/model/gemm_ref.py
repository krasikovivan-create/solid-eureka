"""Эталонная модель GEMM int8 (NumPy) и утилиты для образа общей памяти.

Семантика ускорителя: C[M x N] (int32) = A[M x K] (int8) @ B[K x N] (int8),
знаковые операнды, накопление по модулю 2^32 (int32 с переполнением).
"""
from __future__ import annotations

import numpy as np


def gemm_ref(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Точный эталон: произведение в int64, затем приведение к int32 по модулю 2^32."""
    if a.dtype != np.int8 or b.dtype != np.int8:
        raise TypeError("operands must be int8")
    if a.ndim != 2 or b.ndim != 2 or a.shape[1] != b.shape[0]:
        raise ValueError(f"bad shapes {a.shape} @ {b.shape}")
    c64 = a.astype(np.int64) @ b.astype(np.int64)
    return (c64 & 0xFFFFFFFF).astype(np.uint32).view(np.int32)


def gemm_ref_naive(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Независимая (медленная) реализация с явным 32-битным накоплением — для самопроверки эталона."""
    m, k = a.shape
    n = b.shape[1]
    c = np.zeros((m, n), dtype=np.int64)
    for i in range(m):
        for j in range(n):
            acc = 0
            for t in range(k):
                acc = (acc + int(a[i, t]) * int(b[t, j])) & 0xFFFFFFFF
            c[i, j] = acc - (1 << 32) if acc >= (1 << 31) else acc
    return c.astype(np.int32)


def round_up(x: int, a: int) -> int:
    return (x + a - 1) // a * a


def to_hex_lines(image: bytes, bus: int) -> list[str]:
    """Образ памяти -> строки для $readmemh: одно слово шины на строку, байт 0 в младших битах."""
    assert len(image) % bus == 0
    return [image[i:i + bus][::-1].hex() for i in range(0, len(image), bus)]


def from_hex_lines(lines: list[str], bus: int) -> bytes:
    """Разбор вывода $writememh (комментарии и адресные метки пропускаются)."""
    out = bytearray()
    for raw in lines:
        line = raw.split("//")[0].strip()
        if not line or line.startswith("@"):
            continue
        for tok in line.split():
            if any(ch in tok.lower() for ch in "xz"):
                raise ValueError(f"undefined value in memory dump: {tok}")
            out += int(tok, 16).to_bytes(bus, "little")
    return bytes(out)
