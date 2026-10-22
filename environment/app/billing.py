"""园区电费结算核心：分时电量、最大需量、基本电费与电度电费。

金额按分四舍五入，电量按 0.1 kWh 四舍五入写入结算单。
"""

from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

STEP_H = 0.25
PERIODS = ("valley", "flat", "peak", "sharp")
SHAPE = ("valley", "flat", "peak", "sharp", "flat")


def r2(value):
    return float(Decimal(repr(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def r1(value):
    return float(Decimal(repr(float(value))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def parse_bound(text):
    hour, minute = text.split(":")
    return int(hour) * 60 + int(minute)


def format_bound(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def period_of(minute, bounds):
    index = 0
    for bound in bounds:
        if minute >= bound:
            index += 1
    return SHAPE[index]


def period_energy(minutes, loads, bounds):
    """按区间起点把电量归入时段，返回各时段精确电量（kWh）。"""
    out = {name: 0.0 for name in PERIODS}
    for minute, kw in zip(minutes, loads):
        out[period_of(minute, bounds)] += kw * STEP_H
    return out


def measure_demand(cols, mode):
    """月最大需量。

    feeder_sum：各进线分别取本线最大值，再累加。
    simultaneous：先把同一时刻各进线相加，再取最大值。
    """
    if mode == "feeder_sum":
        return sum(max(col) for col in cols)
    if mode == "simultaneous":
        return max(sum(values) for values in zip(*cols))
    raise ValueError(f"未知的需量口径：{mode}")


def basic_charge(contract_kw, measured_kw, rate, floor_kw):
    """基本电费与计费需量。

    计费需量取核定值与保底值中的较大者；实测超过计费需量 105% 的部分
    按两倍单价计收。
    """
    billed = max(contract_kw, floor_kw)
    excess = max(0.0, measured_kw - 1.05 * billed)
    return r2(billed * rate + 2.0 * rate * excess), billed


def month_bill(month, minutes, loads, cols, tariff):
    energy = period_energy(minutes, loads, tariff["bounds"])
    energy_charge = r2(sum(r2(energy[name] * tariff["rates"][name]) for name in PERIODS))
    measured = measure_demand(cols, tariff["demand_mode"])
    basic, billed = basic_charge(
        tariff["contract_kw"], measured, tariff["demand_rate"], tariff["floor_kw"]
    )
    return {
        "month": month,
        "measured_demand_kw": round(measured, 2),
        "contract_demand_kw": round(billed, 2),
        "energy_kwh": {name: r1(energy[name]) for name in PERIODS},
        "energy_charge": energy_charge,
        "basic_charge": basic,
        "total": r2(energy_charge + basic),
    }


def read_interval(path):
    """读取 interval.csv，按 ts 的 YYYY-MM 分组。

    返回 {"feeders": [...], "months": {month: {"minutes": [...], "cols": [[] ...], "loads": [...]}}}
    """
    feeders = []
    months = {}
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        feeders = [name for name in reader.fieldnames if name != "ts"]
        for row in reader:
            stamp = datetime.strptime(row["ts"], "%Y-%m-%dT%H:%M")
            key = stamp.strftime("%Y-%m")
            bucket = months.setdefault(
                key, {"minutes": [], "cols": [[] for _ in feeders], "loads": []}
            )
            bucket["minutes"].append(stamp.hour * 60 + stamp.minute)
            total = 0.0
            for index, name in enumerate(feeders):
                value = float(row[name])
                bucket["cols"][index].append(value)
                total += value
            bucket["loads"].append(total)
    return {"feeders": feeders, "months": months}
