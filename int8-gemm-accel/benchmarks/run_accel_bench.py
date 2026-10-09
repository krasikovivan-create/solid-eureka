"""Замеры ускорителя в RTL-симуляции (Verilator): такты, загрузка массива, простой.

Каждый прогон проверяется против эталона NumPy (побитово). Частоты здесь нет:
операции в секунду считаются в benchmarks/make_report.py по частоте из nextpnr.

    python3 benchmarks/run_accel_bench.py            # всё, результат в benchmarks/data/accel_sim.json
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.gemm_ref import gemm_ref  # noqa: E402
from model.perf_model import Config, estimate  # noqa: E402
from sim.accel_sim import HwConfig, run_gemm  # noqa: E402

MAIN = HwConfig(P=16, MT=128, KMAX=1024, N_DSP=64, WORDS=1 << 19)

WORKLOADS = [
    ("64^3", 64, 64, 64),
    ("128^3", 128, 128, 128),
    ("256^3", 256, 256, 256),
    ("512^3", 512, 512, 512),
    ("MLP 256x1024x1024", 256, 1024, 1024),
    ("малое K 1024x1024x64", 1024, 1024, 64),
    ("GEMV 1x1024x1024", 1, 1024, 1024),
]


def mats(m, n, k, seed):
    rng = np.random.default_rng(seed)
    return (rng.integers(-128, 128, (m, k), dtype=np.int8),
            rng.integers(-128, 128, (k, n), dtype=np.int8))


def one(cfg: HwConfig, name, m, n, k, lat=32, bw=(1, 1), seed=0):
    a, b = mats(m, n, k, seed)
    t0 = time.perf_counter()
    res = run_gemm(a, b, cfg, lat=lat, bw=bw, seed=seed)
    wall = time.perf_counter() - t0
    ok = res.status == "OK" and np.array_equal(res.c, gemm_ref(a, b)) and res.c_padding_intact
    if not ok:
        raise SystemExit(f"MISMATCH in {name} {cfg} lat={lat} bw={bw}: {res.status}")
    p = res.perf
    macs = m * n * k
    est = estimate(Config("x", cfg.P, cfg.MT, cfg.KMAX), m, n, k, mem_latency=lat)
    row = {
        "workload": name, "M": m, "N": n, "K": k, "P": cfg.P, "MT": cfg.MT, "KMAX": cfg.KMAX,
        "lat": lat, "bw_beats_per_cycle": bw[0] / bw[1], "bus_bytes": cfg.bus,
        "verified_bit_exact": ok, **p, "macs": macs,
        "mac_per_cycle": macs / p["cycles"],
        "utilization": macs / (cfg.P * cfg.P * p["cycles"]),
        "array_busy_frac": p["busy"] / p["cycles"],
        "idle_frac": 1 - p["busy"] / p["cycles"],
        "mem_bytes": (p["rd_beats"] + p["wr_beats"]) * cfg.bus,
        "model_est_cycles": est.est_cycles,
        "sim_wall_s": round(wall, 2),
    }
    print(f"{name:24s} P={cfg.P} MT={cfg.MT:3d} lat={lat:3d} bw={bw[0]}/{bw[1]}: "
          f"cycles={p['cycles']:>9,d} util={row['utilization']:.1%} idle={row['idle_frac']:.1%} "
          f"(mem {p['stall_mem']}, acc {p['stall_acc']}, pipe {p['stall_pipe']}, tail {p['tail']}) "
          f"model={est.est_cycles:,} [{wall:.1f}s]", flush=True)
    return row


def main():
    out = {"meta": {
        "simulator": subprocess.run(["verilator", "--version"], capture_output=True, text=True).stdout.strip(),
        "python": platform.python_version(), "numpy": np.__version__,
        "memory_model": "tb/mem_model.sv: fixed latency LAT, shared read+write budget BWNUM/BWDEN beats/cycle",
    }}
    # 1) основная конфигурация, номинальная память (16 Б/такт, задержка 32 такта)
    out["main"] = [one(MAIN, *w) for w in WORKLOADS]
    # 2) чувствительность к пропускной способности и задержке общей памяти
    sweep = []
    for name, m, n, k in [WORKLOADS[2], WORKLOADS[4]]:
        for bw in [(1, 1), (1, 2), (1, 4), (1, 8)]:
            sweep.append(one(MAIN, name, m, n, k, bw=bw))
        for lat in [1, 128, 512]:
            sweep.append(one(MAIN, name, m, n, k, lat=lat))
    out["memory_sweep"] = sweep
    # 3) размер on-chip буфера (MT) при урезанной полосе общей памяти
    buf = []
    for mt in [16, 32, 64, 128]:
        cfg = HwConfig(P=16, MT=mt, KMAX=1024, N_DSP=64, WORDS=1 << 19)
        for bw in [(1, 1), (1, 4)]:
            buf.append(one(cfg, "MLP 256x1024x1024", 256, 1024, 1024, bw=bw))
    out["buffer_sweep"] = buf
    dst = ROOT / "benchmarks" / "data" / "accel_sim.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print("written", dst)


if __name__ == "__main__":
    main()
