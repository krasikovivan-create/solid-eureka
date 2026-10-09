"""Извлекает из лога nextpnr-ecp5 и статистики Yosys частоту и ресурсы -> JSON.

    python3 synth/parse_nextpnr.py build/synth_ecp5_d156 > benchmarks/data/fpga_ecp5.json
"""
import json
import re
import sys
from pathlib import Path


def parse(outdir: Path) -> dict:
    log = (outdir / "nextpnr.log").read_text()
    res = {"device": "LFE5U-85F (CABGA381, speed 6), out-of-context", "dir": str(outdir)}
    freqs = re.findall(r"Max frequency for clock\s+'([^']+)':\s+([\d.]+) MHz \((PASS|FAIL) at ([\d.]+) MHz\)", log)
    if freqs:
        clk, f, verdict, target = freqs[-1]          # последний отчёт — после трассировки
        res.update({"clock": clk, "fmax_mhz": float(f), "timing_verdict": verdict, "target_mhz": float(target)})
    util = {}
    for name, used, total in re.findall(r"Info:\s+(\w+):\s+(\d+)/\s*(\d+)\s+\d+%", log):
        util[name] = {"used": int(used), "total": int(total)}
    for key, used, total in re.findall(r"Info:\s+Total (LUT4s|DFFs):\s+(\d+)/(\d+)", log):
        util[f"Total {key}"] = {"used": int(used), "total": int(total)}
    res["utilisation"] = util
    crit = re.findall(r"Info: Critical path report for clock '[^']+' \(posedge -> posedge\):(.*?)\n\n", log, re.S)
    if crit:
        lines = [ln for ln in crit[-1].splitlines() if "Net" in ln or "Source" in ln or "Sink" in ln]
        res["critical_path_excerpt"] = [ln.strip() for ln in lines[:3] + lines[-3:]]
    stat = outdir / "yosys_stat.txt"
    if stat.exists():
        cells = dict(re.findall(r"^\s+(\w+)\s+(\d+)$", stat.read_text(), re.M))
        res["yosys_cells"] = {k: int(v) for k, v in cells.items()}
    ver = outdir / "versions.txt"
    if ver.exists():
        res["tools"] = ver.read_text().strip().splitlines()
    return res


if __name__ == "__main__":
    print(json.dumps(parse(Path(sys.argv[1])), indent=1))
