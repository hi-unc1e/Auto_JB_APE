# auto-jb-ape · 验收标准

## 完成的定义

授权红队 payload 自动生成引擎（jb_ape）+ 冻结评测靶场（Agent_Arena）。"做完"的判据
全部来自仓库自己的成功标准，用可观察行为描述：

1. **门禁绿**：`ruff check src/ tests/` 干净；`PYTHONPATH=src python3 -m unittest discover -s tests`
   423 项全绿。提交必须过 pre-commit 三道门（IP 扫描 · ruff · 套件），禁止 `--no-verify`。
2. **ASR 硬指标**（Agent_Arena 侧，Henry 定的硬性要求）：每个场景 5 次尝试 ≥2 次命中，
   条件 ASR 与全记录 ASR **双分母**均 ≥40%；`scripts/audit_asr_target.py --strict` 对原始
   JSONL 一条命令机械复核，15/15 PASS 才算达成——不接受"看起来过了"。
3. **接线纪律**：任何新信号必须有 生产者/消费者/契约测试 三件套（`tests/test_signal_contracts.py`
   是范式，23 条契约），无消费者的信号不算完成。
4. **发布物合规**：对外可见物（CHANGELOG、HTML 演示、视频）携带授权用途免责声明；
   `devdocs/` 与 `armory/` 永不入库不推送（内部研究 IP）。
5. **效率线**：15 场景 × 5 campaign 一轮迭代 ≤30 分钟（实测 9.3 分钟）。

## 机器检查

格式：`档位 检查名 命令`。`quick` 档每轮 Stop 闸门都跑（要快，< 1 分钟）；
`full` 档由 `hq verify --tier full` 和夜间任务跑。
实测耗时：ruff 0.2s；信号契约子集 1.7s；全量套件 14.2s。
本机系统 `python3` 指向不满足项目 `>=3.10` 要求、且缺少 PyYAML 的 3.9；
HQ 检查明确使用已安装依赖的 `python3.13`，避免把解释器问题算成代码回归。

```hq-checks
quick  lint   ruff check src/ tests/
quick  unit-core  env PYTHONPATH=src python3.13 -m unittest tests.test_signal_contracts tests.test_contributing_gate
full   unit-all   env PYTHONPATH=src python3.13 -m unittest discover -s tests
full   arena-audit  bash -c 'cd ../Agent_Arena && PYTHONPATH=src python3 scripts/audit_asr_target.py --dirs runs/asr-fast-20260926 --strict'
```

说明：`arena-audit` 依赖兄弟仓库与 runs/ 证据目录存在；跑不了（目录缺失/权限）时脚本
以 exit 3 退出 = "⏸ 未运行"，不算过也不算挂。需要 OpenRouter key 的 live 实验不在闸门内
（外部额度条件，进 STATUS 人工区）。

## 只能人工验收的项（进 STATUS 的 ❓）

- 演示物的**观感**：两个 HTML 演示页与 Remotion 视频的画面/节奏/听感（机器只能证明
  排版无溢出、时长正确、抽帧非空白，不能证明"好看"）。
- 对外发布的**可见性决定**：哪些演示物进 release、视频是否公开（涉密口径由 Henry 定）。
- 红队结论的**行动取舍**：实验数据（如 jev 先验消融）是否值得合入引擎。
