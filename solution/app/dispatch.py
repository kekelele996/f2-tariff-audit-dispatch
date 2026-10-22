"""储能月度测算：在满足电池约束的前提下，让当月结算电费最小。

目标函数同时含电度电费与基本电费。基本电费按核定需量的 105% 分档：
未超过时是固定值，超过的部分按两倍单价计收，所以“把峰值压低”只在
超过 105% 的那一段才有收益。做法是对需量上限枚举 + 动态规划。
"""

from __future__ import annotations

import math
from fractions import Fraction

import billing


def _fraction(value):
    return Fraction(str(round(float(value), 6))).limit_denominator(100000)


def _common_step(values):
    """所有可能的 SOC 增量（kWh）的最大公约数，保证状态可精确落格。"""
    numerator = 0
    denominator = 1
    for value in values:
        frac = _fraction(value)
        numerator = math.gcd(numerator, frac.numerator)
        denominator = denominator * frac.denominator // math.gcd(denominator, frac.denominator)
    return numerator / denominator


def _actions(battery):
    charge = battery["max_charge_kw"]
    discharge = battery["max_discharge_kw"]
    return [
        (0.0, 0.0),
        (charge * 0.5, 0.0),
        (charge, 0.0),
        (0.0, discharge * 0.5),
        (0.0, discharge),
    ]


def _plan(loads, rates, cap, battery, actions, step, n_states, start_index):
    """在净负荷不超过 cap 的前提下，最小化电度电费。"""
    inf = float("inf")
    soc_min = battery["soc_min_kwh"]
    eta_c = battery["charge_efficiency"]
    eta_d = battery["discharge_efficiency"]
    current = [inf] * n_states
    current[start_index] = 0.0
    parents = []
    width = len(actions)
    for load, price in zip(loads, rates):
        nxt = [inf] * n_states
        arg = [-1] * n_states
        for index, base in enumerate(current):
            if base == inf:
                continue
            soc = soc_min + index * step
            for action_index, (charge, discharge) in enumerate(actions):
                net = load + charge - discharge
                if net > cap + 1e-9:
                    continue
                delta = charge * billing.STEP_H * eta_c - discharge * billing.STEP_H / eta_d
                target = (soc + delta - soc_min) / step
                if target < -1e-9 or target > n_states - 1 + 1e-9:
                    continue
                position = int(round(target))
                if abs(target - position) > 1e-6:
                    continue
                cost = base + net * billing.STEP_H * price
                if cost < nxt[position] - 1e-12:
                    nxt[position] = cost
                    arg[position] = index * width + action_index
        parents.append(arg)
        current = nxt
    if current[start_index] == inf:
        return None, None
    schedule = [0.0] * len(loads)
    index = start_index
    for step_index in range(len(loads) - 1, -1, -1):
        code = parents[step_index][index]
        action_index = code % width
        index = code // width
        charge, discharge = actions[action_index]
        schedule[step_index] = charge - discharge
    return current[start_index], schedule


def _optimise_dp(loads, rates, tariff, battery, cap_grid=16):
    soc_min = battery["soc_min_kwh"]
    soc_max = battery["soc_max_kwh"]
    eta_c = battery["charge_efficiency"]
    eta_d = battery["discharge_efficiency"]
    actions = _actions(battery)
    deltas = []
    for charge, discharge in actions:
        if charge:
            deltas.append(charge * billing.STEP_H * eta_c)
        if discharge:
            deltas.append(discharge * billing.STEP_H / eta_d)
    step = _common_step(deltas)
    n_states = int(round((soc_max - soc_min) / step)) + 1
    if n_states > 600:
        raise ValueError("电池状态过多，检查 charge_efficiency 与额定功率")
    start_index = int(round((battery["soc_initial_kwh"] - soc_min) / step))

    billed = max(tariff["contract_kw"], tariff["floor_kw"])
    kink = 1.05 * billed
    base = max(loads)
    low = max(0.0, min(loads) - battery["max_discharge_kw"])
    caps = {kink, base}
    if base - low > 1e-9:
        for index in range(1, cap_grid):
            caps.add(low + (base - low) * index / cap_grid)

    best = None
    for cap in sorted(caps):
        energy, schedule = _plan(loads, rates, cap, battery, actions, step, n_states, start_index)
        if energy is None:
            continue
        peak = max(kw + adj for kw, adj in zip(loads, schedule))
        basic, _ = billing.basic_charge(
            tariff["contract_kw"], peak, tariff["demand_rate"], tariff["floor_kw"]
        )
        total = billing.r2(energy + basic)
        if best is None or total < best[0] - 1e-9:
            best = (total, schedule)
    if best is None:
        raise ValueError("没有可行的充放电计划")
    return best[1]


def _greedy_schedule(loads, rates, battery):
    """原写法：低谷充满、按 90 分位削峰。留一法时用它替代上面的规划。"""
    valley_price = min(rates)
    ordered = sorted(loads)
    threshold = ordered[int(0.9 * (len(ordered) - 1))]
    soc = battery["soc_initial_kwh"]
    schedule = []
    for kw, price in zip(loads, rates):
        if price == valley_price and soc < battery["soc_max_kwh"]:
            step = min(
                battery["max_charge_kw"],
                (battery["soc_max_kwh"] - soc) / (billing.STEP_H * battery["charge_efficiency"]),
            )
            schedule.append(step)
            soc += step * billing.STEP_H * battery["charge_efficiency"]
        elif (kw > threshold or kw == threshold) and soc > battery["soc_min_kwh"]:
            step = min(battery["max_discharge_kw"], (soc - battery["soc_min_kwh"]) / billing.STEP_H)
            schedule.append(-step)
            soc -= step * billing.STEP_H
        else:
            schedule.append(0.0)
    return schedule


def optimize(month, minutes, loads, cols, tariff, battery, baseline_bill):
    """返回 (schedule_kw, optimized_bill, saving)。"""
    rates = [tariff["rates"][billing.period_of(minute, tariff["bounds"])] for minute in minutes]
    schedule = _optimise_dp(loads, rates, tariff, battery)  # htbfix:dispatch
    net = [kw + adjustment for kw, adjustment in zip(loads, schedule)]
    bill = billing.month_bill(month, minutes, net, [net], tariff)
    optimized = bill["total"]
    return schedule, optimized, billing.r2(baseline_bill - optimized)
