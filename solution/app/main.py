"""测点读数汇总（骨架示例的参考实现，出题时整份替换）。

用法：python3 /app/main.py <readings.json>
"""

import json
import sys
from decimal import ROUND_HALF_UP, Decimal


def summarize(readings):
    values = [(item["id"], item["value"]) for item in readings if item["value"] is not None]
    count = len(values)
    total = sum(value for _, value in values)
    mean = float(Decimal(repr(total / count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    max_id, best = None, None
    for rid, value in values:
        if best is None or value > best or (value == best and rid < max_id):
            max_id, best = rid, value
    return {"count": count, "mean": mean, "max_id": max_id}


def main(argv):
    if len(argv) != 2:
        print("usage: python3 /app/main.py <readings.json>", file=sys.stderr)
        return 2
    with open(argv[1], "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    print(json.dumps(summarize(payload["readings"]), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
