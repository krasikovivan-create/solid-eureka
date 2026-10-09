# int8-gemm-accel — прототип ускорителя GEMM int8

`C[M×N] (int32) = A[M×K] (int8) · B[K×N] (int8)`. Устройство: систолический массив 16×16
(weight-stationary), on-chip буферы 304 КиБ (ping-pong), общая память с одной шиной
16 байт/такт. Написано на SystemVerilog, проверено побитово против NumPy, синтезировано
открытыми инструментами (Yosys + nextpnr) под Lattice ECP5 LFE5U-85F.

* Архитектура, варианты и выбор конфигурации — [`docs/architecture.md`](docs/architecture.md)
* Результаты, условия замеров, сравнение — [`benchmarks/results.md`](benchmarks/results.md)

## Структура

| Путь | Что там |
|---|---|
| `rtl/` | RTL, один модуль на файл: `pe`, `skew_lines`, `systolic_array`, `sram_1r1w`, `operand_buffer`, `acc_buffer`, `reg_slice`, `mem_if`, `dma_rd`, `dma_wr`, `sequencer`, `controller`, `gemm_accel_top` |
| `tb/` | Только для симуляции: модель общей памяти (`mem_model.sv`), тестбенч ускорителя (`tb_gemm.sv`), полный перебор PE (`tb_pe.sv`) |
| `model/` | Эталон на NumPy (`gemm_ref.py`), аналитическая модель трафика (`perf_model.py`) |
| `sim/` | Сборка и запуск симуляции из Python (`accel_sim.py`), мутационная проверка тестов |
| `tests/` | pytest: эталон, PE, RTL против эталона |
| `synth/` | Синтез и размещение для ECP5 (`run_ecp5.sh`), разбор отчёта nextpnr |
| `benchmarks/` | Замеры ускорителя в симуляции, база на CPU, генератор таблиц, `results.md` |

## Как воспроизвести

Нужны: Python 3 с `numpy` и `pytest`; Verilator ≥ 5 и/или Icarus Verilog ≥ 12;
для синтеза — Yosys и nextpnr-ecp5. На Ubuntu 24.04:
`apt-get install verilator iverilog yosys nextpnr-ecp5 && pip install numpy pytest threadpoolctl`.

```bash
python3 -m pytest -q                       # все тесты (≈20 с после первой сборки)
python3 sim/mutation_check.py              # тесты ловят внесённые в RTL ошибки
python3 benchmarks/run_accel_bench.py      # такты в симуляции -> benchmarks/data/accel_sim.json
python3 benchmarks/cpu_baseline.py         # база NumPy на этом CPU -> benchmarks/data/cpu_baseline.json
synth/run_ecp5.sh 156 1 100                # Yosys + nextpnr-ecp5 (десятки минут)
python3 synth/parse_nextpnr.py build/synth_ecp5_d156 > benchmarks/data/fpga_ecp5.json
python3 benchmarks/make_report.py          # таблицы -> benchmarks/results_tables.md
```

Один прогон из Python:

```python
import numpy as np
from sim.accel_sim import HwConfig, run_gemm
a = np.random.randint(-128, 128, (100, 70), dtype=np.int8)
b = np.random.randint(-128, 128, (70, 50), dtype=np.int8)
res = run_gemm(a, b, HwConfig(P=16, MT=128, KMAX=1024, N_DSP=156))
res.c, res.perf          # int32-результат и счётчики (такты, работа, простои)
```

## Ограничения прототипа

`K ≤ 1024`; адреса и шаги строк кратны 16 байтам; выход int32 без реквантизации;
только GEMM (свёртки — через im2col на хосте); память в симуляции — поведенческая модель,
а не реальный контроллер DRAM; частота — по результатам nextpnr для ПЛИС, а не для ASIC.
