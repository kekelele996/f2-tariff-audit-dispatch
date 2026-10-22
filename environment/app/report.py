#!/usr/bin/env python3
"""园区报告入口：读一个 case 目录，写出结算复算与储能测算的 JSON。

    python3 /app/report.py <case_dir> --out <json_path>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import billing
import dispatch
import infer

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def tariff_block(tariff, contract_kw):
    return {
        "boundaries": [billing.format_bound(value) for value in tariff["bounds"]],
        "rates": {name: tariff["rates"][name] for name in billing.PERIODS},
        "demand_rate": tariff["demand_rate"],
        "contract_demand_kw": None if contract_kw is None else round(contract_kw, 2),
    }


def audit_report(case, case_dir, data):
    bills_in = read_json(case_dir / "bills.json")
    price_list = read_json(case_dir / "price_list.json")
    tariff = infer.infer_tariff(case_dir, data, bills_in, price_list, case["site"])
    bills_out = []
    for bill in bills_in:
        month = bill["month"]
        bucket = data["months"][month]
        one = dict(tariff)
        one["contract_kw"] = tariff["contracts"][month]
        bills_out.append(
            billing.month_bill(month, bucket["minutes"], bucket["loads"], bucket["cols"], one)
        )
    return {
        "case_id": case["case_id"],
        "kind": "audit",
        "tariff": tariff_block(tariff, None),
        "bills": bills_out,
        "plan": None,
    }


def plan_report(case, case_dir, data):
    contract = read_json(case_dir / "contract.json")
    battery = read_json(case_dir / "battery.json")
    month = case["plan_month"]
    bucket = data["months"][month]
    floor_kw = 0.4 * case["site"]["transformers_kva"]
    tariff = {
        "demand_mode": "feeder_sum",
        "bounds": infer.parse_bounds(contract["boundaries"]),
        "rates": dict(contract["rates"]),
        "demand_rate": contract["demand_rate"],
        "floor_kw": floor_kw,
        "contract_kw": max(contract["declared_demand_kw"], floor_kw),
    }
    baseline = billing.month_bill(
        month, bucket["minutes"], bucket["loads"], bucket["cols"], tariff
    )
    schedule, optimized, saving = dispatch.optimize(
        month, bucket["minutes"], bucket["loads"], bucket["cols"], tariff, battery, baseline["total"]
    )
    return {
        "case_id": case["case_id"],
        "kind": "plan",
        "tariff": tariff_block(tariff, tariff["contract_kw"]),
        "bills": [],
        "plan": {
            "baseline_bill": baseline["total"],
            "optimized_bill": optimized,
            "saving": saving,
            "schedule_kw": [round(value, 3) for value in schedule],
        },
    }


def build_report(case_dir):
    case_dir = Path(case_dir)
    case = read_json(case_dir / "case.json")
    data = billing.read_interval(case_dir / "interval.csv")
    if case["kind"] == "audit":
        return audit_report(case, case_dir, data)
    if case["kind"] == "plan":
        return plan_report(case, case_dir, data)
    raise ValueError(f"未知的 case 类型：{case['kind']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="园区电费复核与储能测算")
    parser.add_argument("case_dir", help="用例目录，内含 case.json 与 interval.csv")
    parser.add_argument("--out", required=True, help="输出 JSON 路径")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.case_dir)
    except (OSError, ValueError, KeyError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
