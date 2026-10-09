"""Аналитическая (не потактовая) модель ускорителя GEMM int8.

Используется на шаге проектирования для оценки трафика памяти, требуемой
пропускной способности и загрузки массива. Это ОЦЕНКА по формулам из
docs/architecture.md, а не измерение; измеренные такты берутся из RTL-симуляции.

Обозначения: C[M x N] (int32) = A[M x K] (int8) @ B[K x N] (int8).
P   - размер систолического массива P x P (weight-stationary);
MT  - число строк A в панели, хранимой в on-chip буфере (A-буфер, ping-pong);
KMAX- максимальное K, на которое рассчитаны буферы;
шина памяти - P байт за такт (одно слово буфера = один такт шины).
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

ACC_BYTES = 4  # int32 результат


@dataclass(frozen=True)
class Config:
    name: str
    P: int
    MT: int
    KMAX: int

    @property
    def bus_bytes(self) -> int:
        return self.P

    @property
    def a_buf_bytes(self) -> int:  # два слота по MT x KMAX
        return 2 * self.MT * self.KMAX

    @property
    def b_buf_bytes(self) -> int:  # два слота по KMAX x P
        return 2 * self.KMAX * self.P

    @property
    def acc_buf_bytes(self) -> int:  # два слота по MT x P int32
        return 2 * self.MT * self.P * ACC_BYTES

    @property
    def total_buf_bytes(self) -> int:
        return self.a_buf_bytes + self.b_buf_bytes + self.acc_buf_bytes

    @property
    def peak_mac_per_cycle(self) -> int:
        return self.P * self.P

    @property
    def psum_width(self) -> int:
        # |a*b| <= 2^14 -> 16 бит со знаком; сумма P произведений -> +log2(P) бит
        return 16 + math.ceil(math.log2(self.P))

    @property
    def pe_ff_bits(self) -> int:
        # a(8) + два регистра веса (2x8) + частичная сумма + флаги valid/sel
        return 8 + 16 + self.psum_width + 2


@dataclass(frozen=True)
class Estimate:
    macs: int
    bytes_a: int
    bytes_b: int
    bytes_c: int
    compute_cycles: int
    mem_cycles: int
    prologue_cycles: int
    epilogue_cycles: int

    @property
    def bytes_total(self) -> int:
        return self.bytes_a + self.bytes_b + self.bytes_c

    @property
    def est_cycles(self) -> int:
        return max(self.compute_cycles, self.mem_cycles) + self.prologue_cycles + self.epilogue_cycles

    def required_bw(self) -> float:
        """Байт/такт, необходимых, чтобы массив не простаивал из-за памяти."""
        return self.bytes_total / self.compute_cycles


def estimate(cfg: Config, M: int, N: int, K: int, mem_latency: int = 32) -> Estimate:
    if K > cfg.KMAX:
        raise ValueError(f"K={K} > KMAX={cfg.KMAX}")
    P, MT, bus = cfg.P, cfg.MT, cfg.bus_bytes
    kw = math.ceil(K / P)            # слов (= k-блоков) на строку A
    panels = math.ceil(M / MT)
    jblk = math.ceil(N / P)
    # Трафик считается по занятости шины (неполные слова занимают целый такт).
    bytes_a = M * kw * bus
    bytes_b = panels * jblk * K * bus           # каждая B-панель K x P читается для каждой панели A
    bytes_c = M * jblk * (P * ACC_BYTES)        # строка тайла C: P int32
    compute = 0
    for p in range(panels):
        mt_eff = min(MT, M - p * MT)
        compute += jblk * kw * max(mt_eff, P)   # блок весов P x P грузится за P тактов
    mem = math.ceil((bytes_a + bytes_b + bytes_c) / bus)
    mt0 = min(MT, M)
    prologue = mem_latency + mt0 * kw + K       # первая панель A и первая панель B
    mt_last = M - (panels - 1) * MT
    epilogue = 2 * P + mt_last * (P * ACC_BYTES // bus)  # конвейер массива + запись последнего тайла C
    return Estimate(M * N * K, bytes_a, bytes_b, bytes_c, compute, mem, prologue, epilogue)


VARIANTS = [
    Config("V1: 8x8, 148 KiB", P=8, MT=64, KMAX=1024),
    Config("V2: 16x16, 304 KiB", P=16, MT=128, KMAX=1024),
    Config("V3: 32x32, 1.2 MiB", P=32, MT=256, KMAX=2048),
]

WORKLOADS = [
    ("128^3", 128, 128, 128),
    ("256^3", 256, 256, 256),
    ("512^3", 512, 512, 512),
    ("MLP M256 K1024 N1024", 256, 1024, 1024),
    ("малое K: M1024 N1024 K64", 1024, 1024, 64),
    ("GEMV: M1 K1024 N1024", 1, 1024, 1024),
]


def report() -> str:
    lines = []
    lines.append("| Вариант | Задача | MAC | Трафик, КиБ | Треб. Б/такт | Шина Б/такт | Оценка тактов | Оценка загрузки |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for cfg in VARIANTS:
        for wname, M, N, K in WORKLOADS:
            if K > cfg.KMAX:
                continue
            e = estimate(cfg, M, N, K)
            util = e.macs / (cfg.peak_mac_per_cycle * e.est_cycles)
            lines.append(
                f"| {cfg.name} | {wname} | {e.macs:,} | {e.bytes_total / 1024:,.0f} | "
                f"{e.required_bw():.1f} | {cfg.bus_bytes} | {e.est_cycles:,} | {util:.0%} |"
            )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", action="store_true", help="вывести таблицу вариантов x задач")
    ap.add_argument("--P", type=int)
    ap.add_argument("--MT", type=int)
    ap.add_argument("--KMAX", type=int, default=1024)
    ap.add_argument("--mnk", type=int, nargs=3)
    args = ap.parse_args()
    if args.mnk and args.P and args.MT:
        cfg = Config("custom", args.P, args.MT, args.KMAX)
        print(estimate(cfg, *args.mnk))
        return
    print(report())
    print()
    for cfg in VARIANTS:
        print(f"{cfg.name}: A={cfg.a_buf_bytes // 1024} KiB, B={cfg.b_buf_bytes // 1024} KiB, "
              f"ACC={cfg.acc_buf_bytes // 1024} KiB, total={cfg.total_buf_bytes / 1024:.0f} KiB, "
              f"PE FF bits={cfg.pe_ff_bits}, psum={cfg.psum_width} bit")


if __name__ == "__main__":
    main()
