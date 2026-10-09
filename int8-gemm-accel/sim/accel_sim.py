"""Сборка и запуск RTL-симуляции ускорителя (Verilator или Icarus Verilog).

    from sim.accel_sim import HwConfig, run_gemm
    res = run_gemm(a, b, HwConfig(), simulator="verilator")
    res.c, res.perf

Образ общей памяти: A, B, C построчно, шаги строк выровнены по ширине шины;
байты паддинга и область C заполняются случайным «мусором», чтобы проверить
маскирование хвостов (A по K) и стробы записи (C по N).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from model.gemm_ref import from_hex_lines, round_up, to_hex_lines

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
RTL_FILES = sorted((ROOT / "rtl").glob("*.sv"))
TB_FILES = [ROOT / "tb" / "mem_model.sv", ROOT / "tb" / "tb_gemm.sv"]


@dataclass(frozen=True)
class HwConfig:
    P: int = 16
    MT: int = 128
    KMAX: int = 1024
    N_DSP: int | None = None      # None -> все PE с умножителем для DSP
    WORDS: int = 1 << 19          # размер модели памяти в словах шины

    @property
    def bus(self) -> int:
        return self.P

    @property
    def n_dsp(self) -> int:
        return self.P * self.P if self.N_DSP is None else self.N_DSP

    def tag(self) -> str:
        return f"P{self.P}_MT{self.MT}_K{self.KMAX}_D{self.n_dsp}_W{self.WORDS}"

    def params(self) -> dict[str, int]:
        return {"P": self.P, "MT": self.MT, "KMAX": self.KMAX, "N_DSP": self.n_dsp, "WORDS": self.WORDS}


@dataclass
class SimResult:
    status: str                       # OK / ERROR / TIMEOUT
    perf: dict[str, int]
    c: np.ndarray | None = None
    c_padding_intact: bool | None = None
    stdout: str = ""
    layout: dict[str, int] = field(default_factory=dict)


def _sources_digest() -> str:
    h = hashlib.sha256()
    for f in RTL_FILES + TB_FILES:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def build(cfg: HwConfig, simulator: str = "verilator") -> list[str]:
    """Собирает симулятор для конфигурации (с кэшированием) и возвращает команду запуска."""
    out = BUILD / f"{simulator}_{cfg.tag()}"
    stamp = out / "stamp"
    digest = _sources_digest()
    if simulator == "verilator":
        exe = out / "Vtb_gemm"
        cmd = [str(exe)]
    elif simulator == "icarus":
        exe = out / "tb_gemm.vvp"
        cmd = ["vvp", "-n", str(exe)]
    else:
        raise ValueError(simulator)
    if exe.exists() and stamp.exists() and stamp.read_text() == digest:
        return cmd
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    srcs = [str(f) for f in RTL_FILES + TB_FILES]
    if simulator == "verilator":
        gparams = [f"-G{k}={v}" for k, v in cfg.params().items()]
        args = ["verilator", "--binary", "--timing", "-O3", "-Wno-fatal", "-Wno-lint", "-Wno-style",
                "--x-assign", "fast", "--x-initial", "fast",
                "--top-module", "tb_gemm", "-Mdir", str(out), "-o", "Vtb_gemm",
                "-j", str(os.cpu_count() or 2), "-CFLAGS", "-O2", *gparams, *srcs]
    else:
        gparams = [f"-Ptb_gemm.{k}={v}" for k, v in cfg.params().items()]
        args = ["iverilog", "-g2012", "-s", "tb_gemm", "-o", str(exe), *gparams, *srcs]
    proc = subprocess.run(args, cwd=out, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{simulator} build failed:\n{proc.stdout}\n{proc.stderr}")
    stamp.write_text(digest)
    return cmd


def run_gemm(a: np.ndarray, b: np.ndarray, cfg: HwConfig = HwConfig(), simulator: str = "verilator",
             lat: int = 32, bw: tuple[int, int] = (1, 1), pad_rows: tuple[int, int, int] = (0, 0, 0),
             garbage: bool = True, repeat: int = 1, seed: int = 0,
             overrides: dict[str, int] | None = None, timeout_cycles: int = 50_000_000) -> SimResult:
    """Прогоняет C = A @ B в RTL-симуляции и возвращает результат и счётчики.

    pad_rows: дополнительные слова шины в конце строк A, B, C (проверка lda/ldb/ldc > минимума).
    overrides: прямые значения регистров (например, для проверки ошибок конфигурации).
    """
    assert a.dtype == np.int8 and b.dtype == np.int8
    m, k = a.shape
    k2, n = b.shape
    assert k == k2
    bus = cfg.bus
    lda = round_up(max(k, 1), bus) + pad_rows[0] * bus
    ldb = round_up(max(n, 1), bus) + pad_rows[1] * bus
    ldc = round_up(max(4 * n, 1), bus) + pad_rows[2] * bus
    addr_a = 0
    addr_b = round_up(addr_a + m * lda, 256)
    addr_c = round_up(addr_b + k * ldb, 256)
    end = round_up(addr_c + m * ldc, bus)
    if end > cfg.WORDS * bus:
        raise ValueError(f"memory image {end} B exceeds model size {cfg.WORDS * bus} B")

    rng = np.random.default_rng(seed)
    image = rng.integers(0, 256, end, dtype=np.uint8) if garbage else np.zeros(end, dtype=np.uint8)
    for i in range(m):
        image[addr_a + i * lda: addr_a + i * lda + k] = a[i].view(np.uint8)
    for t in range(k):
        image[addr_b + t * ldb: addr_b + t * ldb + n] = b[t].view(np.uint8)

    regs = {"M": m, "N": n, "K": k, "ADDR_A": addr_a, "ADDR_B": addr_b, "ADDR_C": addr_c,
            "LDA": lda, "LDB": ldb, "LDC": ldc}
    if overrides:
        regs.update(overrides)

    cmd = build(cfg, simulator)
    with tempfile.TemporaryDirectory(prefix="gemmsim_") as tmp:
        memfile = Path(tmp) / "mem.hex"
        outfile = Path(tmp) / "c_out.hex"
        memfile.write_text("\n".join(to_hex_lines(image.tobytes(), bus)) + "\n")
        plus = [f"+MEMFILE={memfile}", f"+OUTFILE={outfile}", f"+LAT={lat}",
                f"+BWNUM={bw[0]}", f"+BWDEN={bw[1]}", f"+REPEAT={repeat}", f"+TIMEOUT={timeout_cycles}"]
        plus += [f"+{key}={val}" for key, val in regs.items()]
        proc = subprocess.run(cmd + plus, capture_output=True, text=True, cwd=tmp)
        stdout = proc.stdout + proc.stderr
        if proc.returncode != 0:
            raise RuntimeError(f"simulation failed (rc={proc.returncode}):\n{stdout[-4000:]}")
        mres = re.search(r"RESULT\s+(\w+)", stdout)
        status = mres.group(1) if mres else "NORESULT"
        perf = {name: int(val) for name, val in re.findall(r"PERF (\w+) (\d+)", stdout)}
        res = SimResult(status=status, perf=perf, stdout=stdout,
                        layout={"lda": lda, "ldb": ldb, "ldc": ldc,
                                "addr_a": addr_a, "addr_b": addr_b, "addr_c": addr_c})
        if status == "OK":
            region = np.frombuffer(from_hex_lines(outfile.read_text().splitlines(), bus), dtype=np.uint8)
            assert region.size == m * ldc, (region.size, m * ldc)
            rows = region.reshape(m, ldc)
            res.c = rows[:, :4 * n].copy().view("<i4").astype(np.int32)
            orig = image[addr_c: addr_c + m * ldc].reshape(m, ldc)
            res.c_padding_intact = bool(np.array_equal(rows[:, 4 * n:], orig[:, 4 * n:]))
        return res
