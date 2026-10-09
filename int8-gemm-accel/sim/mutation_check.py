"""Мутационная проверка тестов: вносит в RTL по одной известной ошибке и проверяет,
что pytest её ловит. Запуск из корня проекта: python3 sim/mutation_check.py

Мутация «WL на 1 такт раньше (P-2)» по выводу в docs/architecture.md (раздел 3)
безопасна (в правиле запас 1 такт) и не должна ловиться; P-3 — должна.
"""
import subprocess, sys, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
MUTS = [
 ("rtl/pe.sv", "assign s3 = pp6 - pp7;", "assign s3 = pp6 + pp7;", "LUT multiplier sign"),
 ("rtl/dma_rd.sv", "if (b >= cur_mask) masked", "if (b > cur_mask) masked", "K-tail mask off-by-one"),
 ("rtl/dma_wr.sv", "if (i >= last_bytes) wr_strb[i] = 1'b0;", "wr_strb[i] = 1'b1;", "write strobe ignores N tail"),
 ("rtl/acc_buffer.sv", "assign wdata[c*32 +: 32] = s1_first ?", "assign wdata[c*32 +: 32] = 1'b0 ?", "accumulator ignores 'first'"),
 ("rtl/sequencer.sv", "(st_since >= (PL+1)'(P - 1))", "(st_since >= (PL+1)'(P - 2))", "WL starts 1 cycle earlier (P-2, predicted SAFE)"),
 ("rtl/sequencer.sv", "(st_since >= (PL+1)'(P - 1))", "(st_since >= (PL+1)'(P - 3))", "WL starts 2 cycles earlier (P-3, predicted UNSAFE)"),
 ("rtl/systolic_array.sv", "localparam int LAT = 2 * P - 1;", "localparam int LAT = 2 * P;", "token delay off by one"),
]
sel = "test_pe or main_random or small_fuzz or main_extremes or main_memory or job_sequence"
for f, old, new, desc in MUTS:
    p = ROOT / f; orig = p.read_text()
    assert old in orig, (f, old)
    p.write_text(orig.replace(old, new, 1))
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-k", sel, "-p", "no:cacheprovider"], capture_output=True, text=True, cwd=ROOT)
        last = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l][-1:]
        print(f"{desc:55s} -> {'CAUGHT' if r.returncode else 'not caught'} {last}")
    finally:
        p.write_text(orig)
