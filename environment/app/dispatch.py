"""储能测算：按低谷充电、高峰削峰的规则排一个日循环计划。

排出来的计划用于给客户估算配置储能后能省多少电费。
"""

from __future__ import annotations

import billing


def optimize(month, minutes, loads, cols, tariff, battery, baseline_bill):
    """返回 (schedule_kw, optimized_bill, saving)。"""
    valley_price = min(tariff["rates"].values())
    ordered = sorted(loads)
    threshold = ordered[int(0.9 * (len(ordered) - 1))]
    soc = battery["soc_initial_kwh"]
    schedule = []
    for kw, minute in zip(loads, minutes):
        price = tariff["rates"][billing.period_of(minute, tariff["bounds"])]
        if price == valley_price and soc < battery["soc_max_kwh"]:
            step = min(
                battery["max_charge_kw"],
                (battery["soc_max_kwh"] - soc) / (billing.STEP_H * battery["charge_efficiency"]),
            )
            schedule.append(step)
            soc += step * billing.STEP_H * battery["charge_efficiency"]
        elif kw >= threshold and soc > battery["soc_min_kwh"]:
            step = min(battery["max_discharge_kw"], (soc - battery["soc_min_kwh"]) / billing.STEP_H)
            schedule.append(-step)
            soc -= step * billing.STEP_H
        else:
            schedule.append(0.0)

    throughput = sum(-value for value in schedule if value < 0) * billing.STEP_H
    spread = max(tariff["rates"].values()) - valley_price
    saving = billing.r2(throughput * spread * 0.9)
    return schedule, billing.r2(baseline_bill - saving), saving
