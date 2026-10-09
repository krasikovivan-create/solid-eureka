"""Базовая реализация тех же вычислений на CPU (NumPy) и замер времени.

Задача та же, что у ускорителя: вход A[M x K], B[K x N] в int8, выход C в int32,
побитово равный эталону (каждый вариант проверяется).

Варианты:
  numpy_int32      A.astype(int32) @ B.astype(int32). Целочисленный matmul в NumPy
                   не использует BLAS; семантика int32 с переполнением та же.
  numpy_f32_blas   через float32 (OpenBLAS sgemm) и обратно в int32. Точно, пока
                   |частичные суммы| <= 2^24, т. е. при K <= 1024 (проверяется).
  numpy_f64_blas   через float64 (dgemm), точно для любых K здесь.
  numpy_f32_blas_1thread  то же, что numpy_f32_blas, но OpenBLAS ограничен 1 потоком.
  f32_kernel_only  только sgemm на заранее преобразованных float32-входах, без
                   преобразований — самый выгодный для CPU замер.

Методика: 2 прогона прогрева, затем не меньше 7 прогонов и не меньше ~1 с на вариант
(не больше 51 прогона); в отчёт идут медиана, минимум, межквартильный размах.

    python3 benchmarks/cpu_baseline.py      # -> benchmarks/data/cpu_baseline.json
"""
from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.gemm_ref import gemm_ref  # noqa: E402

WORKLOADS = [
    ("64^3", 64, 64, 64),
    ("128^3", 128, 128, 128),
    ("256^3", 256, 256, 256),
    ("512^3", 512, 512, 512),
    ("MLP 256x1024x1024", 256, 1024, 1024),
    ("малое K 1024x1024x64", 1024, 1024, 64),
    ("GEMV 1x1024x1024", 1, 1024, 1024),
]


def v_int32(a, b):
    return np.matmul(a.astype(np.int32), b.astype(np.int32))


def v_f32(a, b):
    return np.matmul(a.astype(np.float32), b.astype(np.float32)).astype(np.int32)


def v_f64(a, b):
    return np.matmul(a.astype(np.float64), b.astype(np.float64)).astype(np.int32)


def timeit(fn, *args, min_runs=7, max_runs=51, min_total=1.0):
    for _ in range(2):
        fn(*args)
    times = []
    t_start = time.perf_counter()
    while len(times) < max_runs and (len(times) < min_runs or time.perf_counter() - t_start < min_total):
        t0 = time.perf_counter_ns()
        fn(*args)
        times.append((time.perf_counter_ns() - t0) / 1e9)
    q = statistics.quantiles(times, n=4)
    return {"median_s": statistics.median(times), "min_s": min(times),
            "iqr_s": q[2] - q[0], "runs": len(times)}


def cpu_info():
    info = {"platform": platform.platform(), "machine": platform.machine(),
            "python": platform.python_version(), "numpy": np.__version__,
            "logical_cpus": os.cpu_count()}
    try:
        lscpu = subprocess.run(["lscpu"], capture_output=True, text=True).stdout
        for line in lscpu.splitlines():
            key, _, val = line.partition(":")
            if key.strip() in ("Model name", "Hypervisor vendor", "Core(s) per socket", "Thread(s) per core",
                               "L2 cache", "L3 cache", "CPU max MHz"):
                info[key.strip()] = val.strip()
            if key.strip() == "Flags":
                info["avx512_vnni"] = "avx512_vnni" in val
                info["avx2"] = "avx2" in val
    except OSError:
        pass
    try:
        blas = np.show_config(mode="dicts")["Build Dependencies"]["blas"]
        info["blas"] = f'{blas.get("name")} {blas.get("version")}'
    except Exception:  # noqa: BLE001
        pass
    try:
        from threadpoolctl import threadpool_info
        info["threadpools"] = [{k: d[k] for k in ("internal_api", "num_threads", "version", "architecture")
                                if k in d} for d in threadpool_info()]
    except ImportError:
        pass
    return info


def main():
    rng = np.random.default_rng(0)
    rows = []
    for name, m, n, k in WORKLOADS:
        a = rng.integers(-128, 128, (m, k), dtype=np.int8)
        b = rng.integers(-128, 128, (k, n), dtype=np.int8)
        ref = gemm_ref(a, b)
        variants = {"numpy_int32": v_int32, "numpy_f32_blas": v_f32, "numpy_f64_blas": v_f64}
        for vname, fn in variants.items():
            exact = bool(np.array_equal(fn(a, b), ref))
            t = timeit(fn, a, b)
            rows.append({"workload": name, "M": m, "N": n, "K": k, "variant": vname,
                         "bit_exact": exact, **t, "gops": 2 * m * n * k / t["median_s"] / 1e9})
            print(f"{name:24s} {vname:16s} median={t['median_s'] * 1e3:10.3f} ms "
                  f"({rows[-1]['gops']:8.2f} GOPS, runs={t['runs']}, exact={exact})", flush=True)
        try:
            from threadpoolctl import threadpool_limits
            with threadpool_limits(limits=1, user_api="blas"):
                exact = bool(np.array_equal(v_f32(a, b), ref))
                t = timeit(v_f32, a, b)
            rows.append({"workload": name, "M": m, "N": n, "K": k, "variant": "numpy_f32_blas_1thread",
                         "bit_exact": exact, **t, "gops": 2 * m * n * k / t["median_s"] / 1e9})
            print(f"{name:24s} {'f32_blas_1thread':16s} median={t['median_s'] * 1e3:10.3f} ms "
                  f"({rows[-1]['gops']:8.2f} GOPS, runs={t['runs']}, exact={exact})", flush=True)
        except ImportError:
            pass
        af, bf = a.astype(np.float32), b.astype(np.float32)
        t = timeit(np.matmul, af, bf)
        rows.append({"workload": name, "M": m, "N": n, "K": k, "variant": "f32_kernel_only",
                     "bit_exact": bool(np.array_equal(np.matmul(af, bf).astype(np.int32), ref)),
                     **t, "gops": 2 * m * n * k / t["median_s"] / 1e9})
        print(f"{name:24s} {'f32_kernel_only':16s} median={t['median_s'] * 1e3:10.3f} ms "
              f"({rows[-1]['gops']:8.2f} GOPS, runs={t['runs']})", flush=True)
    out = {"meta": cpu_info(), "rows": rows}
    dst = ROOT / "benchmarks" / "data" / "cpu_baseline.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(out["meta"], indent=1, ensure_ascii=False))
    print("written", dst)


if __name__ == "__main__":
    main()
