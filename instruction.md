# 园区电费复核与储能测算

园区能源平台替十几家租户管电费。营销系统每月出一张结算单，平台按自己的口径复算一遍，
差得多的月份要人工核对；另外给签约租户做储能的月度测算，估算装一组电池能省多少电费。

## 现状

复核页上，同一份 15 分钟负荷数据算出来的分时电量和金额，跟结算单对不上：有的月差几分钱，
有的月差几千块。储能测算给出的节省普遍比运维组的实测高，照它排产之后有两家租户当月电费反而涨了。

价格表里那份时段划分是上一版的，今年省内调整过，平台没有跟着改。结算单上给出了分时电量、
两项金额和合计，没有写时段和需量是怎么取的。

## 要交付的内容

改 `/app` 下的模块，入口是 `/app/report.py`：

```
python3 /app/report.py <case_dir> --out <json_path>
```

`case` 目录由 `case.json` 描述，`kind` 有两种：

- `audit`：`interval.csv` 覆盖 12 个月，`bills.json` 是营销系统的结算单，`price_list.json` 是平台缓存的价格表。
- `plan`：`interval.csv` 是计划月的负荷，`contract.json` 是这个站的合同电价，`battery.json` 是电池参数。

`interval.csv` 每行是一个 15 分钟区间，`ts` 为当地时间，后面每一列是一条进线的平均功率，单位 kW。

输出一个 JSON 对象，写到 `--out` 指定的路径：

```json
{
  "case_id": "park-a",
  "kind": "audit",
  "tariff": {
    "boundaries": ["07:45", "10:30", "14:45", "19:30"],
    "rates": {"valley": 0.2112, "flat": 0.4887, "peak": 0.8056, "sharp": 0.995},
    "demand_rate": 43.46,
    "contract_demand_kw": null
  },
  "bills": [
    {
      "month": "2025-01",
      "measured_demand_kw": 740.39,
      "contract_demand_kw": 650.0,
      "energy_kwh": {"valley": 53642.4, "flat": 67973.1, "peak": 50427.5, "sharp": 46763.0},
      "energy_charge": 131701.32,
      "basic_charge": 28249.0,
      "total": 159950.32
    }
  ],
  "plan": null
}
```

`audit` 用例里 `bills` 是 12 条，`plan` 为 `null`；`plan` 用例里 `bills` 是空数组，`plan` 形如：

```json
{
  "baseline_bill": 232231.26,
  "optimized_bill": 225099.07,
  "saving": 7132.19,
  "schedule_kw": [0.0, 0.0, 100.0, "...每个 15 分钟区间一个数"]
}
```

`tariff.contract_demand_kw` 在 `plan` 用例里给数值，`audit` 用例写 `null`，核定需量逐条放在账单里。

## 口径要求

分时时段按四个边界给出，写成 HH:MM。四个边界把一天切成五段，依次是低谷、平段、高峰、尖峰、平段。
`rates` 原样取自价格表。

每条账单给出本月的实测需量、计费需量和四项金额。分时电量按 15 分钟区间的起点归入时段。

金额按分四舍五入，需量保留两位小数，电量保留一位小数。账单里的 `total` 等于 `energy_charge`
加 `basic_charge`。

`plan` 用例里，`baseline_bill` 是不装储能时这个月的结算电费；`optimized_bill` 是按 `schedule_kw`
执行的结算电费，用同一套账单口径算。`saving` 是两者之差。

充放电计划按 15 分钟一个点给出，正数表示充电，长度等于计划月的区间数。

计划对应的月电费按结算口径重算，不是估算。

电池的用法是：充电时从电网取 1 kWh，进入电池 `charge_efficiency` kWh；放电时电池放出 1 kWh，
负荷得到 `discharge_efficiency` kWh。计划要满足 `battery.json` 里的功率上限、荷电状态上下限，
并且计划月结束时回到初始荷电状态。

## 约束

- 只用容器里已有的 Python 标准库，不联网。
- 单个用例 300 秒内跑完。
- 同一份输入重复运行，结果要一致。
- 参数不对或缺少时退出码为 2，不写任何文件。
- case 目录不存在时退出码为 2，不写任何文件。
