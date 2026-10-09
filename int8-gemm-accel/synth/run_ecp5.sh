#!/usr/bin/env bash
# Синтез (Yosys) и размещение/трассировка (nextpnr-ecp5) для Lattice ECP5 LFE5U-85F.
# Использование: synth/run_ecp5.sh [N_DSP] [SEED] [TARGET_MHZ] [ROUTER] [TAG]
# Режим --out-of-context: ускоритель размещается как блок внутри SoC; порты
# памяти и CSR не выводятся на ножки (их ~600, у корпуса CABGA381 только 365 IO).
set -euo pipefail
cd "$(dirname "$0")/.."
N_DSP=${1:-156}
SEED=${2:-1}
FREQ=${3:-100}
ROUTER=${4:-router1}
TAG=${5:-}
OUT=build/synth_ecp5_d${N_DSP}${TAG}
mkdir -p "$OUT"
git rev-parse --short HEAD > "$OUT/git_rev.txt" 2>/dev/null || true
git status --porcelain rtl >> "$OUT/git_rev.txt" 2>/dev/null || true
yosys -V | tee "$OUT/versions.txt"
nextpnr-ecp5 --version 2>&1 | head -1 | tee -a "$OUT/versions.txt"
yosys -l "$OUT/yosys.log" -q -p "
  read_verilog -sv $(ls rtl/*.sv | tr '\n' ' ');
  hierarchy -top gemm_accel_top -chparam P 16 -chparam MT 128 -chparam KMAX 1024 -chparam N_DSP ${N_DSP};
  synth_ecp5 -top gemm_accel_top -json $OUT/gemm.json;
  tee -o $OUT/yosys_stat.txt stat"
nextpnr-ecp5 --85k --package CABGA381 --speed 6 --out-of-context \
  --json "$OUT/gemm.json" --freq "$FREQ" --seed "$SEED" --router "$ROUTER" \
  --report "$OUT/nextpnr_report.json" --log "$OUT/nextpnr.log"
grep -E "Max frequency|Device utilisation|TRELLIS_SLICE|TRELLIS_FF|TRELLIS_COMB|DP16KD|MULT18X18D|Total LUT4s|Total DFFs" "$OUT/nextpnr.log" | tail -20
