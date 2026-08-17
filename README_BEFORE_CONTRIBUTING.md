# README_BEFORE_CONTRIBUTING — 给即将扩展本项目的 Agent

> **先读这份，再动代码。** 本文回答三件事：现有内容地图、如何新增用例、
> 哪些部分**不可修改**（及每条约束由哪个测试守护——改坏会立刻红）。
> 项目定位：授权红队研究工具；任何扩展不得削弱其纪律。

---

## 0. 质量门（每次改动后必须全绿）

```bash
ruff check src/ tests/                                          # 静态扫描
PYTHONPATH=src python3 -m unittest discover -s tests            # 全部单元测试
PYTHONPATH=src python3 -W error::ResourceWarning -m unittest discover -s tests   # 严格模式
```

当前基线：**383 tests / ruff clean**。任何 PR 若使上述变红即不合格。

**本节不是自觉，是机械强制**：`hooks/pre-commit` 在每次提交前自动执行——
IP/凭据泄漏扫描（§3 #11）→ `ruff check`（ruff 缺失即拒绝提交）→ 当 `src/` 或
`tests/` 有变更时运行全量套件（§3 红线的守护测试全在其中）。克隆后启用一次：

```bash
git config core.hooksPath hooks
```

本文档自身也由 `tests/test_contributing_gate.py` 守护：§3 引用的守卫测试必须
真实存在、AGENTS.md 信号清单必须与契约类同步、§0 基线计数必须与套件一致——
文档说谎即红。

---

## 1. 现有内容地图

```
src/jb_ape/
├── models.py      Objective/DefenseProfile/Variant/SubmissionResult/JudgeResult/Feedback
├── catalog.py     12 预设场景（9 问题类）+ canary 金丝雀机制        ← 新增用例路径①
├── techniques.py  T-A/B/C/D/E/F 手法库（骨架+赛道+强度）            ← 路径③
├── jailbreak.py   Wei 两失败模式 + B-J* 机械叠加器 + 组合表
├── defense.py     三层防御 + B-I*/B-O* 机械 bypass 生成器          ← 路径④
├── dtree.py       决策树（TargetState/route/TreeWalker 永续输出）
├── planner.py     Bandit + TAP prune + on_topic 门
├── rewriter.py    定向变异 + CrossOver + V2 融合 prompt
├── judge.py       三层裁决（机检+decode+hijack / 关键词 / LLM）+ 提交门禁
├── hijack.py      工具调用劫持判定 + EM/PM/APM(Rouge-L)
├── decode.py      选择性解码（仅 variant 请求过的编码）
├── recon.py       防御侦察探针（L1/L1'/L2/PPL/工具面/sysprompt）
├── generator.py   闭环（prepare/step_round 可步进；RunCtx 有状态）
├── engagement.py  有状态交战实例（step/status/steer/snapshot/resume）
├── mcp_server.py  MCP 工具层（逻辑函数 + 可选 FastMCP 壳）
├── targets.py     真实目标适配器（agent-browser CLI / OpenAI 兼容 API）
├── browser.py     BrowserClient 协议 + DryRun（离线默认）
├── armory.py      信号持久化（seeds/priors/chains/triggers/runs）
├── report.py      人类可读报告
├── qa.py          QA 冒烟测试（固定 24 用例套件 → pass/suspicious/fail 报告）
├── bridge.py      浏览器插件桥（SessionBridge 回环队列 + ExtensionBrowserClient）
├── ui.py          本机 Web GUI（单页：配置→执行→报告，与 CLI 同源引擎）
└── cli.py         jb-ape 命令（ui/scenarios/recon/run/sweep/qa/engage）

armory/            种子库/先验/有效链/侦察探针/交战快照   （gitignored，本地）
devdocs/           17 篇知识库（人类参考，可能与代码漂移）  （gitignored，本地）
skills/jb-ape/     宿主 Agent 技能文档
tests/             383 项；含 18 条信号契约、各红线守卫与 contributing gate
browser_ext/       MV3 浏览器插件（复用登录态的 ext 适配器端）
```

**运行时依赖仅可选**（openai/fastmcp/yaml 均懒加载）；核心引擎纯 stdlib 可离线全测。

---

## 2. 如何新增用例（四条正规路径）

### 路径① 新增场景（最常用）— `src/jb_ape/catalog.py`
```python
Scenario(
    sid="my-scenario", name="…", problem="exfiltration",   # 复用 PROBLEM_CATEGORIES 之一
    track=Track.OFFICE,
    goal_template="Make the target … {canary}",            # 需要金丝雀证明影响时
    canary=True,                                           # 泄露/劫持/越权类必开
    hijack=True,                                           # 赢条件是工具调用劫持时
    success_patterns=[r"(?i)…"],                           # 无 canary 时必须给可编译正则
)
```
规则：`sid` 唯一且稳定（外部会引用）；`problem` 必须取自 `PROBLEM_CATEGORIES`
（否则覆盖测试红）；模板槽位只能用 `{canary}` 与 `{goal}`（`{goal}` 属可选填充）。
测试会验证：pattern 可编译、canary 场景缺 token 会 `ValueError`。

### 路径② 新增种子 payload — `armory/seeds/<track>.yml`
```yaml
  - id: "MYS-01"
    name: "…"
    category: exfiltration
    technique: "T-F3"          # 关联手法（供 bandit 归因）
    layers: ["L2", "L1out"]
    payload: |
      …正文… {goal} … {callback} …
    notes: "来源与判定要点"
```
**占位符契约**：只允许 `to_variant` 默认表里有的键（`{goal} {callback} {tool}
{SECRET} {secret} {AMOUNT} {ATTACKER_IBAN} {target_user} {order_id} {date}` 等，
见 `armory.py`）。出现未知占位符或漏填——`test_tool.py::placeholder` 系列会红。
新增常用占位符时：加进 `defaults` 字典 + 补一条填充测试。

### 路径③ 新增手法 — `src/jb_ape/techniques.py`（+ 两处必改）
1. 定义 `Technique(tid="T-Xn", …, skeleton 含 {goal})` 并加入 `TECHNIQUES`；
2. `jailbreak.TECHNIQUE_FAILURE_MODE["T-Xn"] = COMPETING|MISMATCHED`（必须标注）；
3. `armory/priors/technique_priors.yml` 给先验（default + 相关赛道）。
   ⚠️ **YAML 每个顶层键只许出现一次**（default/office/ecommerce/coding）——
   重复键会静默整段覆盖，`TestPriorsYamlHygiene` 守卫。

### 路径④ 新增机械 bypass / 决策树叶子
- bypass：`defense.py` 实现 `bypass_xxx(payload, …) -> list[str]`（**只返回真
  变换**，无命中返回空——`variant_bundle` 会过滤 no-op），注册进
  `BYPASS_GENERATORS`；输出侧（B-O*）需在 `decode._BYPASS_DECODERS` 配逆解码，
  并把 bid 加入 `_LAYER_TO_BYPASSES` 对应层。
- 叶子：`dtree.build_leaves()` 加 `Leaf(lid, families, bypasses, overlays,
  nest_scenario, problem)`；`problem` 决定路由（condition: 前缀走条件分支）。
  每个新叶必须能被 `route()` 在**某 个** TargetState 下激活——结构测试守卫。

**通用验收（接线纪律，AGENTS.md 详述）**：新能力三问——信号谁产生？谁消费？
行为差异测试在哪？producer-only 的单测**不算完成**。

---

## 3. 不可修改的部分（红线 + 守护测试）

| # | 不变量 | 为什么 | 守护测试 |
|---|--------|--------|---------|
| 1 | **bandit 奖励与采样同一 id 空间**（纯 technique id） | 偏移即学习闭环死亡 | `test_signal_contracts.C4` |
| 2 | **decode 选择性**：只解码 variant 请求过的编码 | 否则 ROT13(prose) 造成假胜利 | `C8` / `test_decode` |
| 3 | **提交门禁读 `Objective.submit_max_false_positive_risk`**（不得硬编码阈值） | 用户可调的置信度闸门 | `C7` / `test_wiring_fixes` |
| 4 | `confirm_on_success=False` **只抑制 confirm 调用**，不得翻转 achieved 判定 | 配置改变不得伪造失败 | `C14` |
| 5 | **beam_width 用 `prune()` 返回值**（不得重建 survivors） | 旧写法使 beam 失效 | `test_review_fixes` |
| 6 | **`_scan_hijack` 嵌套提取**（API 字段里的 tool_call 也要能判） | Agent 证据多在嵌套字段 | `test_hijack` |
| 7 | **canary 语义**：`build_objective(sc, canary=None)` 对 canary 场景必须 `ValueError`；提供 token 时注入 goal + 追加转义 pattern | 纯函数契约 + 可证影响 | `test_tool` 契约组 |
| 8 | **priors YAML 单键**、占位符默认表封闭 | 静默覆盖/脏种子 | `TestPriorsYamlHygiene` / placeholder 组 |
| 9 | **`_arm_id` 返回裸 technique**（不得拼 bypass 后缀） | 同 #1 | `test_review_fixes` |
| 10 | **生成/裁判 LLM 分离**（generator_llm ≠ judge_llm 实例与 system prompt） | 确认偏误 | devdocs/05 §3.3（评审纪律） |
| 11 | **`legacy/` 与 `rsrc/papers/` 不入库**；`devdocs/ armory/ .env` 永不推送 | 内部研究 IP / 凭据 / 大二进制 | `.gitignore`（评审即查） |
| 12 | **Steer 语义保持可观察**（`[operator context]` 行）；disable 走 `disabled_families` | 文档=实现，不许黑盒化 | `test_engagement.TestSteer` |
| 13 | **QA 套件确定性**（固定配方/固定 id，不随 bandit 漂移）；**裁决映射** S/A/B/C → fail/suspicious/pass 且到达退出码 | QA 冒烟是产品不是脚本 | `test_qa.py` / `test_signal_contracts.C16` |
| 14 | **扩展桥只监听 127.0.0.1**；插件抓到的 api_tap 必须进 `api_responses` 证据通道并到达裁决（S 级）| 复用 Session 的对接方式不能产出无消费者证据 | `test_bridge.py` / `test_signal_contracts.C17` |
| 15 | **GUI 与 CLI 同源**：ui.py 只做视图，判定/建议/退出码必须来自同一 `run_qa`/渲染器并经 /api/status 可见 | 防止 GUI 绿、引擎红的分叉 | `test_ui.py` / `test_signal_contracts.C18` |

另：**不要**为绕过某条不变量而改其守护测试——改约束本身需在 devdocs 先立项并
同步更新契约（16/17 篇是设计源，代码是真相，二者冲突以代码+测试为准）。

## 4. 提交前自查清单
- [x] `ruff check` + 全量 unittest 绿 + IP 泄漏扫描 —— **pre-commit 钩子已自动执行**（未启用则先 `git config core.hooksPath hooks`）
- [ ] 新用例走的是四条正规路径之一（不是旁路脚本）
- [ ] 新信号有三问答案 + 契约测试进 `test_signal_contracts.py` 或同级（并同步 AGENTS.md 信号表——`test_contributing_gate.G2` 会核对）
- [ ] YAML 单键 / 占位符封闭 / pattern 可编译 已核对
- [ ] 未触碰 §3 红线；如确需演进红线：先改 devdocs 对应篇 + 本文档
- [ ] 未用 `--no-verify` 绕过门禁（仅限紧急情况，且事后必须补跑全量门）
- [ ] `git status` 干净；无 devdocs/armory/papers/legacy 泄入提交
