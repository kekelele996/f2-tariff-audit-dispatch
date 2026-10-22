#!/usr/bin/env bash
# 参考解：用 solution/app/ 下的完整实现替换 /app 里的同名模块。
# 每个难点的改法、依据和独立复算写在 NOTES.md；这里只负责安装和留一法开关。
#
# 留一法：HTB_SKIP=<难点 id>[,<难点 id>...] 时把这些难点的修复退回原写法，其余照装。
#   harbor run -p <包> -a oracle --ae HTB_SKIP=difficulty_1
# 正式 Oracle 不设这个变量。退回用精确片段替换，每段必须恰好命中一次，否则直接失败。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
install -m 0644 "$HERE/app/infer.py" /app/infer.py
install -m 0644 "$HERE/app/dispatch.py" /app/dispatch.py

SKIP="${HTB_SKIP:-}" /usr/local/bin/python3 - /app/infer.py /app/dispatch.py <<'PY'
import os
import sys
from pathlib import Path

REVERT = {
    "difficulty_1": [
        (
            "    demand_mode = _infer_mode(months, data, bills_by_month, rate, floor_kw)  # htbfix:mode",
            '    demand_mode = "simultaneous"  # htbfix:mode',
        ),
        (
            "    contracts = _fit_contracts(months, bills_by_month, measured, rate, floor_kw)  # htbfix:contract",
            "    contracts = {month: round(measured[month], 2) for month in months}  # htbfix:contract",
        ),
    ],
    "difficulty_2": [
        (
            "    bounds, weekend_flat = _infer_bounds(months, data, bills_by_month)  # htbfix:bounds",
            '    bounds, weekend_flat = parse_bounds(price_list["default_boundaries"]), True  # htbfix:bounds',
        ),
    ],
    "difficulty_3": [
        (
            "    schedule = _optimise_dp(loads, rates, tariff, battery)  # htbfix:dispatch",
            "    schedule = _greedy_schedule(loads, rates, battery)  # htbfix:dispatch",
        ),
    ],
}

skip = [item for item in os.environ.get("SKIP", "").split(",") if item]
unknown = sorted(set(skip) - set(REVERT))
if unknown:
    sys.exit(f"HTB_SKIP 里有未知难点：{unknown}")

targets = [Path(sys.argv[1]), Path(sys.argv[2])]
for key in skip:
    for fixed, original in REVERT[key]:
        hits = 0
        for target in targets:
            text = target.read_text(encoding="utf-8")
            count = text.count(fixed)
            if count == 0:
                continue
            if count != 1:
                sys.exit(f"{key} 的片段在 {target.name} 出现 {count} 次，应为 1")
            target.write_text(text.replace(fixed, original), encoding="utf-8")
            hits += 1
        if hits != 1:
            sys.exit(f"{key} 的片段命中 {hits} 个文件，应为 1")
        print(f"留一法：{key} 退回原写法", file=sys.stderr)
PY

chown runner:runner /app/infer.py /app/dispatch.py 2>/dev/null || true
