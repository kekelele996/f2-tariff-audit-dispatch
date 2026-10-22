"""复核模块：把结算单的口径还原成一套可复用的电价参数。

平台上线时直接按价格表里的默认时段、以及“按实测最大需量”的简化口径写的，
还没有做参数反演。复核模块负责回答两件事：这个站的历史账单是按哪一套
时段划分算的；每个月的基本电费对应多大的核定需量。
"""

from __future__ import annotations

import billing


def parse_bounds(texts):
    return tuple(billing.parse_bound(text) for text in texts)


def infer_tariff(case_dir, data, bills, price_list, site):
    """返回台账口径：需量统计方式、时段边界、电价、每月核定需量。"""
    months = [bill["month"] for bill in bills]
    bounds = parse_bounds(price_list["default_boundaries"])
    demand_mode = "simultaneous"
    contracts = {}
    for month in months:
        measured = billing.measure_demand(data["months"][month]["cols"], demand_mode)
        contracts[month] = round(measured, 2)
    return {
        "demand_mode": demand_mode,
        "bounds": bounds,
        "rates": dict(price_list["energy_rates"]),
        "demand_rate": price_list["demand_rate"],
        "floor_kw": 0.4 * site["transformers_kva"],
        "contracts": contracts,
    }
