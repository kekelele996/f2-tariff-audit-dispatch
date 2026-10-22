"""复核模块：从历史结算单与 15 min 数据反推结算口径。

三件事：
1. 分时时段：用各月分时电量反推四个时段边界（15 min 网格）。
2. 需量口径：两种进线汇总方式里，只有一种能同时复现全部基本电费。
3. 核定需量：由基本电费反解，允许年内按抄表月变更一次。
"""

from __future__ import annotations

import billing

TOL_KWH = 0.6
TOL_CENTS = 0.06


def parse_bounds(texts):
    return tuple(billing.parse_bound(text) for text in texts)


def _slot_prefix(minutes, loads):
    slots = [0.0] * 96
    for minute, kw in zip(minutes, loads):
        slots[minute // 15] += kw * billing.STEP_H
    prefix = [0.0]
    for value in slots:
        prefix.append(prefix[-1] + value)
    return prefix


def _infer_bounds(months, data, bills_by_month):
    """枚举 (b1,b2,b3,b0)，用分时电量把不可能的组合尽早剪掉。"""
    prefixes = {
        month: _slot_prefix(data["months"][month]["minutes"], data["months"][month]["loads"])
        for month in months
    }

    def between(month, start, end):
        return prefixes[month][end] - prefixes[month][start]

    def close(month, start, end, name):
        return abs(between(month, start, end) - bills_by_month[month]["energy_kwh"][name]) <= TOL_KWH

    found = []
    for b1 in range(2, 94):
        for b2 in range(b1 + 1, 95):
            if not all(close(month, b1, b2, "peak") for month in months):
                continue
            for b3 in range(b2 + 1, 96):
                if not all(close(month, b2, b3, "sharp") for month in months):
                    continue
                for b0 in range(1, b1):
                    if not all(close(month, 0, b0, "valley") for month in months):
                        continue
                    ok = all(
                        abs(
                            between(month, b0, b1) + between(month, b3, 96)
                            - bills_by_month[month]["energy_kwh"]["flat"]
                        )
                        <= TOL_KWH
                        for month in months
                    )
                    if ok:
                        found.append((b0 * 15, b1 * 15, b2 * 15, b3 * 15))
    if len(found) != 1:
        raise ValueError(f"时段反演得到 {len(found)} 个解，需要恰好一个")
    return found[0]


def _month_contract_candidates(charge, measured, rate, floor_kw):
    """单月内与基本电费相容的计费需量；两个分支分别按“未超”和“超 105%”求解。"""
    guesses = (charge / rate, (2.0 * rate * measured - charge) / (1.1 * rate))
    out = set()
    for guess in guesses:
        billed = max(guess, floor_kw)
        if billed <= 0:
            continue
        value, _ = billing.basic_charge(billed, measured, rate, floor_kw)
        if abs(value - charge) <= TOL_CENTS:
            out.add(round(billed, 2))
    return out


def _intersect(sets):
    sets = list(sets)
    if not sets:
        return set()
    common = set(sets[0])
    for item in sets[1:]:
        common &= item
    return common


def _fit_contracts(months, bills_by_month, measured, rate, floor_kw):
    """按抄表月切至多两段，每段的候选交集就是该段的核定需量。"""
    per_month = []
    for month in months:
        per_month.append(
            _month_contract_candidates(
                bills_by_month[month]["basic_charge"], measured[month], rate, floor_kw
            )
        )
    if any(not item for item in per_month):
        return None

    best = None
    for cut in range(1, len(months) + 1):
        left = _intersect(per_month[:cut])
        right = _intersect(per_month[cut:]) if cut < len(months) else set()
        if not left or (cut < len(months) and not right):
            continue
        size = len(left) + (len(right) if cut < len(months) else 0)
        if best is None or size < best[0]:
            best = (size, cut, left, right)
    if best is None:
        return None

    _, cut, left, right = best
    if len(left) > 1 or len(right) > 1:
        return None
    left_value = sorted(left)[0]
    right_value = sorted(right)[0] if cut < len(months) else None
    contracts = {}
    for index, month in enumerate(months):
        contracts[month] = left_value if index < cut else right_value
    return contracts


def _infer_mode(months, data, bills_by_month, rate, floor_kw):
    """两种进线汇总方式里，选出能复现全部基本电费的那一种。"""
    fitted = []
    for mode in ("feeder_sum", "simultaneous"):
        measured = {
            month: billing.measure_demand(data["months"][month]["cols"], mode)
            for month in months
        }
        contracts = _fit_contracts(months, bills_by_month, measured, rate, floor_kw)
        if contracts is not None:
            fitted.append((mode, contracts))
    if len(fitted) != 1:
        raise ValueError(f"需量口径反演得到 {len(fitted)} 个可行口径，需要恰好一个")
    return fitted[0][0]


def infer_tariff(case_dir, data, bills, price_list, site):
    """返回台账口径：需量统计方式、时段边界、电价、每月核定需量。"""
    months = [bill["month"] for bill in bills]
    bills_by_month = {bill["month"]: bill for bill in bills}
    rate = price_list["demand_rate"]
    floor_kw = 0.4 * site["transformers_kva"]

    bounds = _infer_bounds(months, data, bills_by_month)  # htbfix:bounds
    demand_mode = _infer_mode(months, data, bills_by_month, rate, floor_kw)  # htbfix:mode

    measured = {
        month: billing.measure_demand(data["months"][month]["cols"], demand_mode)
        for month in months
    }
    contracts = _fit_contracts(months, bills_by_month, measured, rate, floor_kw)  # htbfix:contract
    if contracts is None:
        raise ValueError("基本电费与任何一种核定需量都不相容")
    return {
        "demand_mode": demand_mode,
        "bounds": bounds,
        "rates": dict(price_list["energy_rates"]),
        "demand_rate": rate,
        "floor_kw": floor_kw,
        "contracts": contracts,
    }
