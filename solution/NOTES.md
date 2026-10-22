# 参考解说明

## 三个难点

| 编号 | 错误认知 | 正确知识 | 对应测试（tests/scoring.json） |
|---|---|---|---|
| difficulty_1 |  |  |  |
| difficulty_2 |  |  |  |
| difficulty_3 |  |  |  |

## 参考解文件

- `solution/app/<与 environment/app 同名的文件>`：完整的正确实现（≥ 80 行独立代码，审核器按同名文件统计改动行数）。
- `solve.sh`：只负责安装与留一法开关；`HTB_SKIP` 用精确片段把对应修复退回原写法。

## 关键步骤

1. 待填写。

## 核心公式与独立复算

- 解析推导：`research/derivations.md` 第几节
- 独立数值复核：`research/verify_*.py`，命令与输出见 `research/claims.json`
- 两条路径的差异：……；最终容差：……

## 容差依据

- 正常抖动上限：……
- 典型错误解偏差：……
- 取值理由：……

## 权重依据

- gate 测试（不计分）：入口能跑、参数错误退出码……
- difficulty_1 合计 0.xx：理由……
- difficulty_2 合计 0.xx：理由……
- difficulty_3 合计 0.xx：理由……

## 数据来源

- 真实数据：来源、脱敏方式、记录位置
- 生成数据：业务模型、生成规则、随机种子、复现命令
- 以上说明均不在 `environment/` 内

## 答案隔离

- [ ] 镜像内没有 `tests/`、`solution/`、`.git/`、缓存和备份
- [ ] 注释、文件名、变量名、数据元信息没有答案提示
- [ ] Dockerfile 没有先复制正确版本再改坏
