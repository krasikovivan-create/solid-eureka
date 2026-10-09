"""Сводит измерения в таблицы: benchmarks/results_tables.md.

Источники (все — измерения этого проекта):
  benchmarks/data/accel_sim.json   такты из RTL-симуляции (run_accel_bench.py)
  benchmarks/data/fpga_ecp5.json   Fmax и ресурсы после nextpnr-ecp5 (synth/parse_nextpnr.py)
  benchmarks/data/cpu_baseline.json время NumPy на CPU (cpu_baseline.py)
Время ускорителя = такты / Fmax (частота только из отчёта nextpnr).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "benchmarks" / "data"


def load(name):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else None


def fmt_t(seconds: float) -> str:
    if seconds >= 1:
        return f"{seconds:.3f} s"
    if seconds >= 1e-3:
        return f"{seconds * 1e3:.3f} ms"
    return f"{seconds * 1e6:.1f} µs"


def main():
    acc, fpga, cpu = load("accel_sim.json"), load("fpga_ecp5.json"), load("cpu_baseline.json")
    out = []
    fmax = fpga["fmax_mhz"] * 1e6 if fpga and "fmax_mhz" in fpga else None

    out.append("## Ускоритель: такты (RTL-симуляция, Verilator) и время при Fmax из nextpnr\n")
    if fmax:
        out.append(f"Fmax = {fpga['fmax_mhz']:.2f} МГц ({fpga['device']}); пик массива = "
                   f"{2 * 256 * fmax / 1e9:.2f} GOPS (2 оп. на MAC × 256 MAC/такт).\n")
    out.append("| Задача | Такты | MAC/такт | Загрузка массива | Простой ядра | из них: память / запись C / смена весов / хвост | "
               "Время | GOPS |")
    out.append("|---|---:|---:|---:|---:|---|---:|---:|")
    for r in acc["main"]:
        t = r["cycles"] / fmax if fmax else None
        gops = 2 * r["macs"] / t / 1e9 if t else None
        c = r["cycles"]
        brk = (f"{r['stall_mem'] / c:.1%} / {r['stall_acc'] / c:.1%} / "
               f"{r['stall_pipe'] / c:.1%} / {r['tail'] / c:.1%}")
        out.append(f"| {r['workload']} | {c:,} | {r['mac_per_cycle']:.1f} | {r['utilization']:.1%} | "
                   f"{r['idle_frac']:.1%} | {brk} | {fmt_t(t) if t else '—'} | {f'{gops:.2f}' if gops else '—'} |")

    out.append("\n## Чувствительность к общей памяти (16×16, MT=128)\n")
    out.append("| Задача | Полоса, Б/такт | Задержка, такты | Такты | Загрузка | Простой: память / запись C |")
    out.append("|---|---:|---:|---:|---:|---|")
    for r in acc["memory_sweep"]:
        c = r["cycles"]
        out.append(f"| {r['workload']} | {r['bw_beats_per_cycle'] * r['bus_bytes']:g} | {r['lat']} | {c:,} | "
                   f"{r['utilization']:.1%} | {r['stall_mem'] / c:.1%} / {r['stall_acc'] / c:.1%} |")

    out.append("\n## Размер on-chip буфера A (MT строк), задача MLP 256×1024×1024\n")
    out.append("| MT | SRAM всего, КиБ | Полоса, Б/такт | Трафик памяти, КиБ | Такты | Загрузка |")
    out.append("|---:|---:|---:|---:|---:|---:|")
    for r in acc["buffer_sweep"]:
        sram = (2 * r["MT"] * r["KMAX"] + 2 * r["KMAX"] * r["P"] + 2 * r["MT"] * r["P"] * 4) // 1024
        out.append(f"| {r['MT']} | {sram} | {r['bw_beats_per_cycle'] * r['bus_bytes']:g} | "
                   f"{r['mem_bytes'] / 1024:,.0f} | {r['cycles']:,} | {r['utilization']:.1%} |")

    if cpu:
        out.append("\n## CPU (NumPy): медиана времени\n")
        variants = ["numpy_int32", "numpy_f32_blas_1thread", "numpy_f32_blas", "numpy_f64_blas", "f32_kernel_only"]
        out.append("| Задача | " + " | ".join(variants) + " |")
        out.append("|---|" + "---:|" * len(variants))
        by = {(r["workload"], r["variant"]): r for r in cpu["rows"]}
        for r in acc["main"]:
            cells = []
            for v in variants:
                x = by.get((r["workload"], v))
                cells.append(f"{fmt_t(x['median_s'])} ({x['gops']:.1f} GOPS)" if x else "—")
            out.append(f"| {r['workload']} | " + " | ".join(cells) + " |")

        if fmax:
            out.append("\n## Соотношение: время CPU / время ускорителя (>1 — ускоритель быстрее)\n")
            out.append("| Задача | " + " | ".join(f"vs {v}" for v in variants) + " |")
            out.append("|---|" + "---:|" * len(variants))
            for r in acc["main"]:
                t_acc = r["cycles"] / fmax
                cells = []
                for v in variants:
                    x = by.get((r["workload"], v))
                    cells.append(f"{x['median_s'] / t_acc:.2f}×" if x else "—")
                out.append(f"| {r['workload']} | " + " | ".join(cells) + " |")
    dst = ROOT / "benchmarks" / "results_tables.md"
    dst.write_text("<!-- сгенерировано benchmarks/make_report.py, не редактировать вручную -->\n\n" + "\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
