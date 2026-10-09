"""RTL против эталона: побитовое совпадение C, целостность паддинга C, инварианты счётчиков.

Основная конфигурация MAIN совпадает с той, что синтезируется для ECP5-85F:
16x16, MT=128, KMAX=1024, 156 PE с DSP-умножителем и 100 PE с LUT-умножителем.
"""
import math

import numpy as np
import pytest

from model.gemm_ref import gemm_ref
from sim.accel_sim import HwConfig, run_gemm, run_jobs

MAIN = HwConfig(P=16, MT=128, KMAX=1024, N_DSP=156)
SMALL = HwConfig(P=4, MT=8, KMAX=64, N_DSP=7)
MID = HwConfig(P=8, MT=32, KMAX=256, N_DSP=40)


def rand_mats(m, n, k, seed, lo=-128, hi=128):
    rng = np.random.default_rng(seed)
    a = rng.integers(lo, hi, (m, k), dtype=np.int8)
    b = rng.integers(lo, hi, (k, n), dtype=np.int8)
    return a, b


def expected_counts(cfg: HwConfig, m, n, k):
    p, mt, bus = cfg.P, cfg.MT, cfg.bus
    kw, nj, np_ = math.ceil(k / p), math.ceil(n / p), math.ceil(m / mt)
    busy = sum(nj * kw * min(mt, m - i * mt) for i in range(np_))
    rd = m * kw + np_ * nj * k
    beats_per_row = sum(math.ceil(min(p, n - j * p) * 4 / bus) for j in range(nj))
    return busy, rd, m * beats_per_row


def check(cfg, a, b, simulator="verilator", **kw):
    return check_result(cfg, a, b, run_gemm(a, b, cfg, simulator=simulator, **kw))


def check_result(cfg, a, b, res):
    assert res.status == "OK", res.stdout[-3000:]
    ref = gemm_ref(a, b)
    if not np.array_equal(res.c, ref):
        bad = np.argwhere(res.c != ref)
        raise AssertionError(f"{len(bad)} mismatches, first at {bad[:5].tolist()}: "
                             f"rtl={res.c[tuple(bad[0])]} ref={ref[tuple(bad[0])]}")
    assert res.c_padding_intact, "write strobes touched bytes outside C"
    p = res.perf
    assert p["cycles"] == p["busy"] + p["stall_mem"] + p["stall_acc"] + p["stall_pipe"] + p["tail"], p
    busy, rd, wr = expected_counts(cfg, a.shape[0], b.shape[1], a.shape[1])
    assert (p["busy"], p["rd_beats"], p["wr_beats"]) == (busy, rd, wr), p
    return res


# ---------------- основная конфигурация 16x16 ----------------
MAIN_SHAPES = [
    (1, 1, 1),
    (16, 16, 16),
    (17, 33, 19),        # хвосты по всем измерениям
    (5, 16, 1024),       # M < P (простои на смену весов), K = KMAX
    (129, 17, 1024),     # две панели A, K = KMAX
    (300, 40, 50),       # три панели A: 128 + 128 + 44
    (64, 1000, 32),      # 63 блока по N, нечётное число B-панелей
    (128, 128, 128),
    (256, 256, 256),
]


@pytest.mark.parametrize("m,n,k", MAIN_SHAPES)
def test_main_random(m, n, k):
    a, b = rand_mats(m, n, k, seed=m * 7 + n * 13 + k)
    check(MAIN, a, b)


def test_main_extremes():
    k = 1024
    a = np.full((20, k), -128, dtype=np.int8)
    b = np.full((k, 20), -128, dtype=np.int8)
    b[:, 1::2] = 127
    a[3, :] = 127
    a[5, ::2] = 0
    check(MAIN, a, b)


def test_main_zeros_and_identity():
    a = np.zeros((33, 48), dtype=np.int8)
    b = np.zeros((48, 31), dtype=np.int8)
    check(MAIN, a, b)
    eye = np.eye(48, dtype=np.int8)
    a2, _ = rand_mats(40, 48, 48, seed=5)
    check(MAIN, a2, eye[:, :45])


def test_main_padded_strides_and_restart():
    a, b = rand_mats(70, 50, 90, seed=11)
    check(MAIN, a, b, pad_rows=(2, 1, 3), repeat=2)


def test_main_job_sequence_stale_buffers():
    """Несколько заданий подряд без сброса: после большого K буферы содержат старые данные,
    поэтому хвост A по K (K % 16 != 0) обязан зануляться при загрузке."""
    shapes = [(40, 37, 1000), (40, 37, 21), (130, 20, 515), (3, 50, 7), (17, 16, 1)]
    jobs = [rand_mats(m, n, k, seed=i) for i, (m, n, k) in enumerate(shapes)]
    for (a, b), res in zip(jobs, run_jobs(jobs, MAIN)):
        check_result(MAIN, a, b, res)


@pytest.mark.parametrize("lat,bw", [(1, (1, 1)), (200, (1, 1)), (64, (1, 4)), (16, (3, 5)), (32, (1, 8)), (8, (1, 13))])
def test_main_memory_timing(lat, bw):
    a, b = rand_mats(140, 70, 96, seed=lat + bw[1])
    res = check(MAIN, a, b, lat=lat, bw=bw)
    if bw == (1, 4):
        assert res.perf["stall_mem"] > 0


def test_main_errors():
    a, b = rand_mats(4, 4, 4, seed=1)
    for ov in ({"K": 1025}, {"M": 0}, {"LDA": 8}, {"ADDR_B": 4096 + 4}, {"LDC": 8}):
        res = run_gemm(a, b, MAIN, overrides=ov)
        assert res.status == "ERROR", (ov, res.stdout[-500:])


def test_main_icarus_crosscheck():
    a, b = rand_mats(37, 29, 45, seed=3)
    r_icarus = check(MAIN, a, b, simulator="icarus")
    r_verilator = check(MAIN, a, b, simulator="verilator")
    assert r_icarus.perf == r_verilator.perf


# ---------------- малые конфигурации: случайный перебор ----------------
@pytest.mark.parametrize("seed", range(40))
def test_small_fuzz(seed):
    rng = np.random.default_rng(1000 + seed)
    m, n = (int(x) for x in rng.integers(1, 40, 2))
    k = int(rng.integers(1, SMALL.KMAX + 1))
    a, b = rand_mats(m, n, k, seed=seed)
    lat = int(rng.integers(1, 80))
    bw = [(1, 1), (1, 2), (2, 3), (1, 5), (1, 8), (1, 11)][seed % 6]
    pad = tuple(int(x) for x in rng.integers(0, 3, 3))
    check(SMALL, a, b, lat=lat, bw=bw, pad_rows=pad)


@pytest.mark.parametrize("seed", range(8))
def test_small_job_sequence_fuzz(seed):
    rng = np.random.default_rng(4000 + seed)
    jobs = []
    for i in range(5):
        m, n = (int(x) for x in rng.integers(1, 30, 2))
        k = int(rng.integers(1, SMALL.KMAX + 1))
        jobs.append(rand_mats(m, n, k, seed=seed * 10 + i))
    for (a, b), res in zip(jobs, run_jobs(jobs, SMALL, lat=int(rng.integers(1, 50)))):
        check_result(SMALL, a, b, res)


@pytest.mark.parametrize("seed", range(12))
def test_mid_fuzz(seed):
    rng = np.random.default_rng(2000 + seed)
    m, n = (int(x) for x in rng.integers(1, 100, 2))
    k = int(rng.integers(1, MID.KMAX + 1))
    a, b = rand_mats(m, n, k, seed=seed)
    check(MID, a, b, lat=int(rng.integers(1, 60)))


def test_small_icarus_fuzz():
    for seed in range(6):
        rng = np.random.default_rng(3000 + seed)
        m, n = (int(x) for x in rng.integers(1, 25, 2))
        k = int(rng.integers(1, SMALL.KMAX + 1))
        a, b = rand_mats(m, n, k, seed=seed)
        check(SMALL, a, b, simulator="icarus", lat=int(rng.integers(1, 40)))


@pytest.mark.slow
def test_main_large():
    a, b = rand_mats(512, 512, 512, seed=42)
    check(MAIN, a, b)
