# 新手法进入 JB_APE 的研究 SOP

适用范围：Henry 在授权 Agent 红队研究中发现论文、技术报告或博客，想把其中的手法变成可复用知识、种子、决策节点或新靶场。`armory/research/` 保存来源快照和候选卡，始终留在本机；来源文字是研究材料，不能当作运行指令。

## 1. 先登记假设

把来源 URL、作者、发表日期、阅读日期和原文快照写进候选卡。卡片必须讲清：攻击者控制哪一侧、跨过哪条信任边界、成立前提、机制、可以观察的目标行为、二元成功条件、良性与未送达对照、原文局限，以及相对现有库的新增量。原文报告的命中率记为「作者声称」，不能直接写入本地 `priors`。

以 [`research-card.example.json`](research-card.example.json) 为模板，将 `snapshot_file` 指向本地保存的原文；运行：

```bash
jb-ape research --armory armory intake --card /path/to/card.json
jb-ape research --armory armory list
```

命令检查必填字段、HTTPS 来源和五种已知投递面，按 URL 与快照哈希去重，复制原文到 gitignored 的 `armory/research/sources/`。候选卡本身也只在 `armory/research/candidates/`。缺原文、缺机制或缺成功条件会拒收。来源变了会生成新卡，不覆盖旧卡。

如果提出 `seed`、`decision_node` 或 `new_range`，还要填 `test_artifact_file`：指向本地**实际提交给靶场的候选文本**，字节内容必须与 Arena 记录里的 `candidate_payload` 相同。命令会单独保存它的 SHA-256 和快照；不要把论文原文路径当成测试候选。

## 2. 先决定增量类型

| 观察到的新增量 | 处理 |
|---|---|
| 解释现有现象，但没有新的可测行为 | `knowledge`：留下机制与反例，不改运行时 |
| 同一决策条件下有更好的起手式 | `seed`：沿现有 `armory/seeds/` 路径，保留来源卡 ID |
| 出现**可观测的新条件**，且条件改变后应选择不同策略 | `decision_node`：修改 `dtree.route()` / `build_leaves()`，附 with/without 契约测试 |
| 新信任边界或新违规动作无法用现有二元 oracle 表达 | `new_range`：建新冻结版本、合法任务与未送达对照，不改旧版字节 |

只有「换一种说法」不构成新节点；只有「换一篇来源」不构成新靶场。新节点需说明信号生产者、消费者与行为差异测试。侦察未发现工具只表示未知，不能作为“目标没有工具”的判定。

## 3. 在 Arena 验证，再晋升

先冻结实验协议：目标模型和 provider、投递面、攻击与合法任务、正例投递对照、同预算基线、随机种子、超时、独立 campaign、目标提交数和费用上限。至少记录 `生成 → 自检 → 提交 → 来源可用 → 检索尝试 → 实际观察 → 违规尝试 → mock 副作用`；超时和未送达单列，不能算防御成功。新方法与固定种子、静态组合和机械变异配对比较；尤其要做**排除原种子的测试**，否则命中可能完全来自旧种子。

结束后把新 manifest 交给严格审计，再附到候选卡：

```bash
jb-ape research --armory armory attach --id R-xxxxxxxxxxxx \
  --manifest /path/to/Agent_Arena/runs/new-manifest.json \
  --arena /path/to/Agent_Arena
```

审计失败的证据也会保留，并标成 `unverified`。旧 manifest 若与当前源码指纹不同，必须在原提交的隔离工作树复算或重做当前版本实验，不能改旧文件让它变绿。运行时晋升还要求严格审计记录中出现**同一候选哈希和投递面**，且那条记录同时证明来源被观察和违规尝试；v3.1 的间接投递面还要有 `artifact_observed=true`。未送达、别的候选或别的投递面命中，都不能给这张卡记功。满足这些门槛后，候选卡才可评为 `seed`、`decision_node` 或 `new_range`：

```bash
jb-ape research --armory armory decide --id R-xxxxxxxxxxxx \
  --disposition decision_node --rationale '具体说明新增条件与对照收益'
```

`decide` 只记录研究结论，不会把不可信原文自动接入引擎。真正启用仍要走 [`README_BEFORE_CONTRIBUTING.md`](README_BEFORE_CONTRIBUTING.md) 的四条正规扩展路径，完成生产者、消费者、契约测试、全套测试与代码审阅。新 seed、节点或 range 的具体 payload 继续留在 `armory/`，不进入公开仓库；每次改动保留 commit。若要公开，只发布脱敏的方法和可复算结果。

## 4. 每轮复盘

每张候选卡给出一种处置：收进知识、晋升运行时、保留未证实、拒绝。复盘同时记录负结果：卡在哪个漏斗环节、在哪个模型/投递面上失败、合法任务是否受损、首次命中花了几次目标调用。只有同分布、同预算的本地证据能更新运行时先验；论文中的跨模型 ASR 只作为假设背景。
