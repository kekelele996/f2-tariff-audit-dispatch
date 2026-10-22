"""传感器读数汇总的验收测试（骨架示例，出题时整份替换成本题内容）。

写法约定（审核器 E1/E2/E5/E9 会逐条查）：
- 每个 test_ 函数的 docstring 用「」原样引用题面里的一句话，引用必须能在 instruction.md 里找到；
- 测试体里不写 if/try，分支和异常处理放在模块级辅助函数里；
- 一个难点至少三个计分测试，每个只断言这个难点影响的字段，避免一个修复顺带让别的难点变绿；
- 计分测试在原始（未修）代码上必须全部失败，否则 NOP 拿分；
- gate 测试（入口能跑、参数错误退出码）写进 scoring.json 的 gate_tests，不计分。
期望值来自 research/ 里的独立复核，不要用 solution/ 生成。

本文件以 root 运行；被测程序一律通过 run_candidate() 以 runner 身份、干净环境变量、
独立进程组运行，超时整组结束。
"""

import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path

ENTRY = "/app/main.py"
PYTHON = "/usr/local/bin/python3"
CANDIDATE_USER = "runner"
CANDIDATE_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/home/runner",
    "LANG": "C.UTF-8",
    "TZ": "UTC",
}
CALL_TIMEOUT_SEC = 30


def run_candidate(*args, timeout=CALL_TIMEOUT_SEC):
    """以 runner 身份运行候选入口；超时结束整个进程组并抛出 TimeoutError。"""
    as_root = os.getuid() == 0
    proc = subprocess.Popen(
        [PYTHON, ENTRY, *[str(a) for a in args]],
        cwd="/app",
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


def summarize(readings):
    """把隐藏输入写进随机命名的临时文件（候选只读），返回候选输出的 JSON。"""
    folder = Path(tempfile.mkdtemp(prefix="in-"))
    folder.chmod(0o755)
    case = folder / "readings.json"
    case.write_text(json.dumps({"readings": readings}), encoding="utf-8")
    case.chmod(0o644)
    proc = run_candidate(case)
    assert proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr[-500:]}"
    return json.loads(proc.stdout)


def readings(*pairs):
    return [{"id": rid, "value": value} for rid, value in pairs]


# ---------- gate：入口与契约，不计分 ----------

def test_prints_json_with_three_fields():
    """「程序向标准输出写一个 JSON 对象，只含三个字段」"""
    got = summarize(readings(("a1", 1.0), ("a2", 2.0)))
    assert set(got) == {"count", "mean", "max_id"}


def test_wrong_argument_count_exits_2():
    """「参数个数不对时退出码为 2，不输出 JSON」"""
    proc = run_candidate()
    assert proc.returncode == 2
    assert proc.stdout.strip() == ""


# ---------- 难点 1：均值按四舍五入保留两位 ----------

def test_mean_rounds_half_up_two_thirds():
    """「按四舍五入保留两位小数（0.005 进位）」"""
    assert summarize(readings(("p1", 1), ("p2", 2), ("p3", 2)))["mean"] == 1.67


def test_mean_rounds_half_up_large_values():
    """「按四舍五入保留两位小数（0.005 进位）」"""
    assert summarize(readings(("p1", 5), ("p2", 6), ("p3", 6)))["mean"] == 5.67


def test_mean_exact_half_cent_goes_up():
    """「按四舍五入保留两位小数（0.005 进位）」"""
    assert summarize(readings(("p1", 0.125), ("p2", 0.125)))["mean"] == 0.13


# ---------- 难点 2：并列最大值取字典序最小编号 ----------

def test_tie_picks_smallest_id():
    """「最大值并列时取编号字典序最小的那个」"""
    assert summarize(readings(("a", 5), ("c", 5), ("b", 1)))["max_id"] == "a"


def test_three_way_tie_picks_smallest_id():
    """「最大值并列时取编号字典序最小的那个」"""
    # 最小编号放在中间：只保留第一个或最后一个并列值的写法都过不了
    assert summarize(readings(("z", 9), ("k", 9), ("m", 9)))["max_id"] == "k"


def test_negative_tie_picks_smallest_id():
    """「最大值并列时取编号字典序最小的那个」"""
    assert summarize(readings(("p", -1), ("q", -1), ("r", -5)))["max_id"] == "p"


# ---------- 难点 3：null 读数不计入 ----------

def test_null_not_counted():
    """「value 为 null 的读数不计入」"""
    assert summarize(readings(("a", 1), ("b", None), ("c", 2)))["count"] == 2


def test_null_never_becomes_maximum():
    """「value 为 null 的读数不计入」"""
    assert summarize(readings(("a", -3), ("b", None), ("c", -1)))["max_id"] == "c"


def test_mostly_null_count():
    """「value 为 null 的读数不计入」"""
    assert summarize(readings(("x", None), ("y", 4), ("z", None)))["count"] == 1
