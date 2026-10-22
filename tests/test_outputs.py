"""园区电费复核与储能测算的验收测试。

写法约定：
- 每个 test_ 函数的 docstring 用「」原样引用题面里的一句话；
- 测试体里不写 if/try，分支与异常处理放在模块级辅助函数；
- 期望值由本文件独立实现（账单模型、动态规划）从隐藏用例的参数算出，不读 /app；
- 计分测试在原始代码上必须全部失败；gate 测试（入口、参数错误）不计分。

本文件以 root 运行；被测程序通过 run_candidate() 以 runner 身份、固定环境变量、
独立进程组运行，超时整组结束。
"""

import json
import math
import os
import random
import signal
import subprocess
import tempfile
from calendar import monthrange
from datetime import date
from pathlib import Path

ENTRY = "/app/report.py"
APP_CWD = "/app"
PYTHON = "/usr/local/bin/python3"
CANDIDATE_USER = "runner"
CANDIDATE_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/home/runner",
    "LANG": "C.UTF-8",
    "TZ": "UTC",
}
CALL_TIMEOUT_SEC = 300

PERIODS = ("valley", "flat", "peak", "sharp")
SHAPE = ("valley", "flat", "peak", "sharp", "flat")
STEP_H = 0.25
SOC_STEP = 2.5

_CASES = {}
_RUNS = {}
_ROOT = None


# ---------------- 候选调用 ----------------

def run_candidate(*args, timeout=CALL_TIMEOUT_SEC):
    as_root = os.getuid() == 0
    proc = subprocess.Popen(
        [PYTHON, ENTRY, *[str(arg) for arg in args]],
        cwd=APP_CWD,
        env=CANDIDATE_ENV,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        user=CANDIDATE_USER if as_root else None,
        group=CANDIDATE_USER if as_root else None,
        extra_groups=[] if as_root else None,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise TimeoutError(f"{ENTRY} 超过 {timeout}s")
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def work_root():
    global _ROOT
    if _ROOT is None:
        _ROOT = Path(tempfile.mkdtemp(prefix="htb-"))
        _ROOT.chmod(0o777)
    return _ROOT


def report_of(name):
    if name in _RUNS:
        return _RUNS[name]
    out_dir = work_root() / f"out-{name}"
    out_dir.mkdir(exist_ok=True)
    out_dir.chmod(0o777)
    out_path = out_dir / "report.json"
    proc = run_candidate(_CASES[name]["dir"], "--out", out_path)
    assert proc.returncode == 0, f"{name}: exit={proc.returncode} stderr={proc.stderr[-600:]}"
    assert out_path.exists(), f"{name}: 没有写出 report.json"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    _RUNS[name] = data
    return data


# ---------------- 独立账单实现 ----------------

def r2(value):
    from decimal import Decimal, ROUND_HALF_UP

    return float(Decimal(repr(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def period_of(minute, bounds, flat=False):
    if flat:
        return "flat"
    index = 0
    for bound in bounds:
        if minute >= bound:
            index += 1
    return SHAPE[index]


def weekend_flags(year, month):
    """与 interval.csv 对齐：每天 96 个区间，周六周日为真。"""
    flags = []
    for day in range(1, monthrange(year, month)[1] + 1):
        flag = date(year, month, day).weekday() >= 5
        flags.extend([flag] * 96)
    return flags


def period_energy(minutes, loads, bounds, weekend=None, weekend_flat=False):
    total = {name: 0.0 for name in PERIODS}
    for index, (minute, kw) in enumerate(zip(minutes, loads)):
        flat = bool(weekend_flat and weekend is not None and weekend[index])
        total[period_of(minute, bounds, flat)] += kw * STEP_H
    return total


def measured(cols):
    return sum(max(col) for col in cols)


def basic(contract, demand, rate, floor):
    billed = max(contract, floor)
    over = max(0.0, demand - 1.05 * billed)
    return r2(billed * rate + 2.0 * rate * over), billed


def bill_of(month, minutes, loads, cols, bounds, rates, contract, rate, floor,
            weekend=None, weekend_flat=False):
    energy = period_energy(minutes, loads, bounds, weekend, weekend_flat)
    energy_charge = r2(sum(r2(energy[name] * rates[name]) for name in PERIODS))
    demand = measured(cols)
    charge, billed = basic(contract, demand, rate, floor)
    return {
        "month": month,
        "measured_demand_kw": round(demand, 2),
        "contract_demand_kw": round(billed, 2),
        "energy_kwh": energy,
        "energy_charge": energy_charge,
        "basic_charge": charge,
        "total": r2(energy_charge + charge),
    }


# ---------------- 隐藏用例生成 ----------------

def make_load(seed, year, month, base, two_feeders, park):
    rnd = random.Random(seed * 100000 + month)
    days = monthrange(year, month)[1]
    minutes = []
    rows = []
    for day in range(days):
        weekday = (day + 1) % 7 not in (0, 6)
        for slot in range(96):
            minute = slot * 15
            hour = minute / 60.0
            if park:
                scale = 1.0 + 0.18 * math.cos(2 * math.pi * (month - 7) / 12)
                a = 250.0 * scale
                b = 85.0 * scale
                if weekday and 8.0 <= hour < 11.5:
                    a += 300.0
                if weekday and 17.5 <= hour < 21.0:
                    a += 265.0
                if weekday and 13.0 <= hour < 17.5:
                    a += 120.0
                if 10.0 <= hour < 14.0:
                    b += 185.0 * (1.0 if weekday else 0.55)
                if 19.0 <= hour < 21.5:
                    b += 70.0
                if not weekday:
                    a *= 0.62
                a += rnd.uniform(-16, 16)
                b += rnd.uniform(-7, 7)
                if rnd.random() < 0.0012:
                    a += rnd.uniform(70, 150)
                values = [round(a * base, 3), round(b * base, 3)]
            else:
                a = float(base)
                if weekday and 11.5 <= hour < 13.5:
                    a += 92.0
                if weekday and 18.0 <= hour < 21.0:
                    a += 40.0
                if not weekday:
                    a -= 52.0
                a += rnd.uniform(-14, 14)
                if rnd.random() < 0.0008:
                    a += rnd.uniform(30, 60)
                values = [round(a, 3)]
            if not two_feeders:
                values = values[:1]
            minutes.append(minute)
            rows.append(values)
    return minutes, rows


def write_case(name, spec):
    folder = work_root() / name
    folder.mkdir(exist_ok=True)
    folder.chmod(0o755)
    feeders = ["feeder_a", "feeder_b"][: spec["feeders"]]
    lines = ["ts," + ",".join(feeders)]
    truth = {}
    for month in spec["months"]:
        minutes, rows = spec["loader"](month)
        for index, values in enumerate(rows):
            day = index // 96 + 1
            minute = minutes[index]
            stamp = f"{spec['year']}-{month:02d}-{day:02d}T{minute // 60:02d}:{minute % 60:02d}"
            lines.append(stamp + "," + ",".join(f"{value:.3f}" for value in values))
        truth[f"{spec['year']}-{month:02d}"] = (minutes, [list(column) for column in zip(*rows)])
    (folder / "interval.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder, truth


def random_tariff(seed):
    rnd = random.Random(seed)
    b0 = rnd.randrange(28, 36)
    b1 = rnd.randrange(b0 + 8, b0 + 14)
    b2 = rnd.randrange(56, 62)
    b3 = rnd.randrange(b2 + 14, b2 + 20)
    bounds = (b0 * 15, b1 * 15, b2 * 15, b3 * 15)
    rates = {
        "valley": round(rnd.uniform(0.210, 0.235), 4),
        "flat": round(rnd.uniform(0.460, 0.495), 4),
        "peak": round(rnd.uniform(0.800, 0.860), 4),
        "sharp": round(rnd.uniform(0.960, 1.020), 4),
    }
    rate = round(rnd.uniform(38, 44), 2)
    return bounds, rates, rate


def build_audit(name, seed, base, two_feeders, capacity, declared, change_month, weekend_flat=False):
    bounds, rates, rate = random_tariff(seed)
    floor = 0.4 * capacity
    contracts = {}
    for month in range(1, 13):
        contracts[month] = declared[0] if month < change_month else declared[1]
    spec = {
        "year": 2025,
        "months": list(range(1, 13)),
        "feeders": 2 if two_feeders else 1,
        "loader": lambda month: make_load(seed, 2025, month, base, two_feeders, True),
    }
    folder, truth = write_case(name, spec)
    bills = []
    for month in range(1, 13):
        key = f"2025-{month:02d}"
        minutes, cols = truth[key]
        loads = [sum(values) for values in zip(*cols)]
        flags = weekend_flags(2025, month)
        bill = bill_of(key, minutes, loads, cols, bounds, rates, contracts[month], rate, floor,
                       flags, weekend_flat)
        bills.append(bill)
    payload = []
    for bill in bills:
        payload.append(
            {
                "month": bill["month"],
                "energy_kwh": {key: round(value, 1) for key, value in bill["energy_kwh"].items()},
                "energy_charge": bill["energy_charge"],
                "basic_charge": bill["basic_charge"],
                "total": bill["total"],
            }
        )
    (folder / "bills.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "price_list.json").write_text(
        json.dumps(
            {
                "effective": "2025-01-01",
                "energy_rates": rates,
                "demand_rate": rate,
                "default_boundaries": ["08:00", "11:00", "15:00", "20:00"],
                "period_shape": list(SHAPE),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    (folder / "case.json").write_text(
        json.dumps(
            {
                "case_id": name,
                "kind": "audit",
                "site": {"name": name, "transformers_kva": capacity, "feeders": ["feeder_a", "feeder_b"][: spec["feeders"]]},
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    _CASES[name] = {
        "dir": folder,
        "kind": "audit",
        "bounds": bounds,
        "rates": rates,
        "rate": rate,
        "floor": floor,
        "contracts": contracts,
        "weekend_flat": weekend_flat,
        "bills": bills,
        "months": [f"2025-{month:02d}" for month in range(1, 13)],
        "data": truth,
    }


def build_plan(name, seed, base, declared, capacity):
    bounds, rates, rate = random_tariff(seed)
    month = 7
    spec = {
        "year": 2025,
        "months": [month],
        "feeders": 1,
        "loader": lambda value: make_load(seed, 2025, value, base, False, False),
    }
    folder, truth = write_case(name, spec)
    minutes, cols = truth[f"2025-{month:02d}"]
    battery = {
        "capacity_kwh": 400.0,
        "max_charge_kw": 100.0,
        "max_discharge_kw": 100.0,
        "charge_efficiency": 0.8,
        "discharge_efficiency": 1.0,
        "soc_min_kwh": 40.0,
        "soc_max_kwh": 360.0,
        "soc_initial_kwh": 120.0,
    }
    (folder / "battery.json").write_text(json.dumps(battery, indent=1), encoding="utf-8")
    (folder / "contract.json").write_text(
        json.dumps(
            {
                "declared_demand_kw": declared,
                "demand_rate": rate,
                "demand_window_min": 15,
                "boundaries": [f"{value // 60:02d}:{value % 60:02d}" for value in bounds],
                "rates": rates,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    (folder / "case.json").write_text(
        json.dumps(
            {
                "case_id": name,
                "kind": "plan",
                "site": {"name": name, "transformers_kva": capacity, "feeders": ["feeder_a"]},
                "plan_month": f"2025-{month:02d}",
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    _CASES[name] = {
        "dir": folder,
        "kind": "plan",
        "bounds": bounds,
        "rates": rates,
        "rate": rate,
        "declared": declared,
        "capacity": capacity,
        "floor": 0.4 * capacity,
        "battery": battery,
        "minutes": minutes,
        "cols": cols,
        "loads": list(cols[0]),
        "month": f"2025-{month:02d}",
    }


def load_cases():
    if _CASES:
        return
    build_audit("multi-run", 101, 0.82, True, 1250.0, (650.0, 700.0), 6, weekend_flat=True)
    build_audit("floor-run", 102, 0.92, True, 1800.0, (380.0, 380.0), 13, weekend_flat=False)
    build_plan("plan-base", 201, 500.0, 700.0, 1250.0)
    build_plan("plan-tight", 202, 600.0, 430.0, 1250.0)


# ---------------- 独立最优调度 ----------------

def rate_series(minutes, bounds, rates):
    return [rates[period_of(minute, bounds)] for minute in minutes]


def dp_optimum(loads, prices, contract, rate, floor, battery):
    """按需量上限枚举，再对每个上限做最短路径；与参考实现结构不同。"""
    soc_min = battery["soc_min_kwh"]
    soc_max = battery["soc_max_kwh"]
    eta_c = battery["charge_efficiency"]
    eta_d = battery["discharge_efficiency"]
    power_c = battery["max_charge_kw"]
    power_d = battery["max_discharge_kw"]
    count = int(round((soc_max - soc_min) / SOC_STEP)) + 1
    start = int(round((battery["soc_initial_kwh"] - soc_min) / SOC_STEP))
    moves = [(0.0, 0.0), (power_c * 0.5, 0.0), (power_c, 0.0), (0.0, power_d * 0.5), (0.0, power_d)]
    kink = 1.05 * max(contract, floor)
    top = max(loads)
    bottom = max(0.0, min(loads) - power_d)
    caps = [kink] + [bottom + (top - bottom) * index / 20.0 for index in range(21)]
    best = None
    for cap in caps:
        cost = [math.inf] * count
        cost[start] = 0.0
        links = []
        for load, price in zip(loads, prices):
            nxt = [math.inf] * count
            pick = [0] * count
            for index in range(count):
                base = cost[index]
                if base == math.inf:
                    continue
                soc = soc_min + index * SOC_STEP
                for move_index, (charge, discharge) in enumerate(moves):
                    net = load + charge - discharge
                    if net > cap + 1e-9:
                        continue
                    new_soc = soc + charge * STEP_H * eta_c - discharge * STEP_H / eta_d
                    position = int(round((new_soc - soc_min) / SOC_STEP))
                    if position < 0 or position >= count:
                        continue
                    if abs(new_soc - (soc_min + position * SOC_STEP)) > 1e-6:
                        continue
                    value = base + net * STEP_H * price
                    if value < nxt[position] - 1e-12:
                        nxt[position] = value
                        pick[position] = index * len(moves) + move_index
            links.append(pick)
            cost = nxt
        if cost[start] == math.inf:
            continue
        schedule = []
        position = start
        for time_index in range(len(loads) - 1, -1, -1):
            code = links[time_index][position]
            move_index = code % len(moves)
            position = code // len(moves)
            charge, discharge = moves[move_index]
            schedule.append(charge - discharge)
        schedule.reverse()
        peak = max(load + adjustment for load, adjustment in zip(loads, schedule))
        charge, _ = basic(contract, peak, rate, floor)
        total = r2(cost[start] + charge)
        if best is None or total < best[0]:
            best = (total, schedule)
    return best


def plan_expectation(name):
    case = _CASES[name]
    if "optimum" in case:
        return case["optimum"]
    prices = rate_series(case["minutes"], case["bounds"], case["rates"])
    baseline = bill_of(
        case["month"], case["minutes"], case["loads"], case["cols"], case["bounds"],
        case["rates"], case["declared"], case["rate"], case["floor"],
    )["total"]
    total, schedule = dp_optimum(
        case["loads"], prices, case["declared"], case["rate"], case["floor"], case["battery"]
    )
    case["optimum"] = {"baseline": baseline, "total": total, "schedule": schedule}
    return case["optimum"]


def soc_trace(schedule, battery):
    soc = battery["soc_initial_kwh"]
    trace = [soc]
    for value in schedule:
        if value > 0:
            soc += value * STEP_H * battery["charge_efficiency"]
        else:
            soc += value * STEP_H / battery["discharge_efficiency"]
        trace.append(soc)
    return trace


def feasible(schedule, battery, expected_len):
    if len(schedule) != expected_len:
        return False, f"计划长度 {len(schedule)}，应为 {expected_len}"
    trace = soc_trace(schedule, battery)
    if min(trace) < battery["soc_min_kwh"] - 0.05 or max(trace) > battery["soc_max_kwh"] + 0.05:
        return False, f"SOC 越界 {min(trace):.2f}..{max(trace):.2f}"
    if abs(trace[-1] - battery["soc_initial_kwh"]) > 0.05:
        return False, f"期末 SOC {trace[-1]:.2f} 没有回到 {battery['soc_initial_kwh']}"
    for value in schedule:
        if value > battery["max_charge_kw"] + 1e-6 or value < -battery["max_discharge_kw"] - 1e-6:
            return False, f"功率越界 {value}"
    return True, "ok"


def plan_bill(name, schedule):
    case = _CASES[name]
    net = [load + adjustment for load, adjustment in zip(case["loads"], schedule)]
    return bill_of(
        case["month"], case["minutes"], net, [net], case["bounds"], case["rates"],
        case["declared"], case["rate"], case["floor"],
    )["total"]


# ---------------- gate：入口与契约 ----------------

def test_entry_writes_report_for_audit_case():
    """「python3 /app/report.py <case_dir> --out <json_path>」「输出一个 JSON 对象」"""
    load_cases()
    data = report_of("multi-run")
    assert data["kind"] == "audit"
    assert isinstance(data["bills"], list)
    assert len(data["bills"]) == 12


def test_missing_out_argument_exits_nonzero():
    """「参数不对或缺少时退出码为 2，不写任何文件」"""
    load_cases()
    proc = run_candidate(_CASES["multi-run"]["dir"])
    assert proc.returncode == 2
    assert proc.stdout.strip() == ""


def test_unknown_case_directory_exits_nonzero():
    """「case 目录不存在时退出码为 2，不写任何文件」"""
    load_cases()
    missing = work_root() / "no-such-case"
    out_dir = work_root() / "out-missing"
    out_dir.mkdir(exist_ok=True)
    out_dir.chmod(0o777)
    proc = run_candidate(missing, "--out", out_dir / "report.json")
    assert proc.returncode == 2
    assert not (out_dir / "report.json").exists()


def test_repeat_run_is_identical():
    """「同一份输入重复运行，结果要一致」「只用容器里已有的 Python 标准库，不联网」"""
    load_cases()
    first = report_of("multi-run")
    second_dir = work_root() / "out-repeat"
    second_dir.mkdir(exist_ok=True)
    second_dir.chmod(0o777)
    second_path = second_dir / "report.json"
    proc = run_candidate(_CASES["multi-run"]["dir"], "--out", second_path)
    assert proc.returncode == 0
    second = json.loads(second_path.read_text(encoding="utf-8"))
    assert second == first


# ---------------- 难点 1：需量口径与核定需量 ----------------

def test_measured_demand_uses_feeder_maxima():
    """「每条账单给出本月的实测需量、计费需量和四项金额」"""
    load_cases()
    data = report_of("multi-run")
    case = _CASES["multi-run"]
    got = [bill["measured_demand_kw"] for bill in data["bills"]]
    want = []
    for month in case["months"]:
        minutes, cols = case["data"][month]
        want.append(round(measured(cols), 2))
    assert all(abs(a - b) <= 0.02 for a, b in zip(got, want)), f"{got} != {want}"


def test_contract_demand_recovers_midyear_change():
    """「每条账单给出本月的实测需量、计费需量和四项金额」"""
    load_cases()
    data = report_of("multi-run")
    case = _CASES["multi-run"]
    got = [bill["contract_demand_kw"] for bill in data["bills"]]
    want = [case["contracts"][month] for month in range(1, 13)]
    assert all(abs(a - b) <= 0.05 for a, b in zip(got, want)), f"{got} != {want}"


def test_floor_contract_on_low_load_site():
    """「金额按分四舍五入，需量保留两位小数」"""
    load_cases()
    data = report_of("floor-run")
    case = _CASES["floor-run"]
    got = [bill["contract_demand_kw"] for bill in data["bills"]]
    want = [case["floor"] for _ in range(12)]
    assert all(abs(a - b) <= 0.05 for a, b in zip(got, want)), f"{got} != {want}"
    charges = [bill["basic_charge"] for bill in data["bills"]]
    expect = [case["bills"][index]["basic_charge"] for index in range(12)]
    assert all(abs(a - b) <= 0.05 for a, b in zip(charges, expect)), f"{charges} != {expect}"


# ---------------- 难点 2：分时时段反演 ----------------

def test_boundaries_recovered_for_two_feeder_site():
    """「分时时段按四个边界给出，写成 HH:MM」"""
    load_cases()
    data = report_of("multi-run")
    case = _CASES["multi-run"]
    got = [int(text[:2]) * 60 + int(text[3:]) for text in data["tariff"]["boundaries"]]
    assert got == list(case["bounds"]), f"{got} != {list(case['bounds'])}"


def test_boundaries_recovered_for_floor_site():
    """「分时时段按四个边界给出，写成 HH:MM」"""
    load_cases()
    data = report_of("floor-run")
    case = _CASES["floor-run"]
    got = [int(text[:2]) * 60 + int(text[3:]) for text in data["tariff"]["boundaries"]]
    assert got == list(case["bounds"]), f"{got} != {list(case['bounds'])}"


def test_period_energy_matches_reported_boundaries():
    """「分时电量按 15 分钟区间的起点归入时段」"""
    load_cases()
    data = report_of("multi-run")
    case = _CASES["multi-run"]
    bounds = tuple(int(text[:2]) * 60 + int(text[3:]) for text in data["tariff"]["boundaries"])
    gaps = []
    for index, month in enumerate(case["months"]):
        minutes, cols = case["data"][month]
        loads = [sum(values) for values in zip(*cols)]
        want = period_energy(
            minutes, loads, bounds, weekend_flags(2025, index + 1), case["weekend_flat"]
        )
        got = data["bills"][index]["energy_kwh"]
        for name in PERIODS:
            gaps.append((month, name, got[name] - want[name]))
            gaps.append((month, name, got[name] - case["bills"][index]["energy_kwh"][name]))
    assert len(gaps) == 12 * len(PERIODS) * 2
    worst = max(abs(item[2]) for item in gaps)
    assert worst <= 0.25, f"分时电量最大偏差 {worst}：{max(gaps, key=lambda item: abs(item[2]))}"


# ---------------- 难点 3：储能计划 ----------------

def test_schedule_is_feasible():
    """「充放电计划按 15 分钟一个点给出，正数表示充电」"""
    load_cases()
    data = report_of("plan-base")
    case = _CASES["plan-base"]
    schedule = data["plan"]["schedule_kw"]
    ok, reason = feasible(schedule, case["battery"], len(case["loads"]))
    assert ok, reason


def test_schedule_reaches_optimum_on_base_site():
    """「计划对应的月电费按结算口径重算，不是估算」"""
    load_cases()
    data = report_of("plan-base")
    case = _CASES["plan-base"]
    schedule = data["plan"]["schedule_kw"]
    ok, reason = feasible(schedule, case["battery"], len(case["loads"]))
    assert ok, reason
    expect = plan_expectation("plan-base")
    actual = plan_bill("plan-base", schedule)
    assert abs(data["plan"]["baseline_bill"] - expect["baseline"]) <= 0.05
    assert abs(data["plan"]["optimized_bill"] - actual) <= 0.05
    assert actual <= expect["total"] * 1.01, f"{actual} > {expect['total']}"


def test_schedule_reaches_optimum_with_tight_contract():
    """「计划对应的月电费按结算口径重算，不是估算」"""
    load_cases()
    data = report_of("plan-tight")
    case = _CASES["plan-tight"]
    schedule = data["plan"]["schedule_kw"]
    ok, reason = feasible(schedule, case["battery"], len(case["loads"]))
    assert ok, reason
    expect = plan_expectation("plan-tight")
    actual = plan_bill("plan-tight", schedule)
    assert abs(data["plan"]["optimized_bill"] - actual) <= 0.05
    assert actual <= expect["total"] * 1.01, f"{actual} > {expect['total']}"
