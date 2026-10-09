"""Полный перебор (a, w) для PE: оба варианта умножителя, оба банка весов, Icarus и Verilator."""
import re
import subprocess

import pytest

from sim.accel_sim import BUILD, ROOT

SRCS = [str(ROOT / "rtl" / "pe.sv"), str(ROOT / "tb" / "tb_pe.sv")]


def _run(cmd, cwd):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def _check(out):
    m = re.search(r"PE_TEST errors=(\d+) checks=(\d+)", out)
    assert m, out
    assert int(m.group(2)) == 2 * 256 * 256
    assert int(m.group(1)) == 0, out


def test_pe_exhaustive_icarus():
    d = BUILD / "pe_icarus"
    d.mkdir(parents=True, exist_ok=True)
    _run(["iverilog", "-g2012", "-s", "tb_pe", "-o", "tb_pe.vvp", *SRCS], d)
    _check(_run(["vvp", "-n", "tb_pe.vvp"], d))


def test_pe_exhaustive_verilator():
    d = BUILD / "pe_verilator"
    d.mkdir(parents=True, exist_ok=True)
    _run(["verilator", "--binary", "--timing", "-Wno-fatal", "-Wno-lint", "-Wno-style",
          "--top-module", "tb_pe", "-Mdir", str(d), "-o", "Vtb_pe", *SRCS], d)
    _check(_run([str(d / "Vtb_pe")], d))
