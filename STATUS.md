---
hq: 1
project: auto-jb-ape
theme: 安全研究
value: 研究
state: active
updated: 2026-09-26 23:25
---
# auto-jb-ape · 状态

> 引擎侧 405 测试全绿（含新漏斗信号 #20），master @ a9dc086；jev 消融两轮完成——18× 速度、端到端未过线、
> 暂不接入；Arena 侧新增 delivery 三轴矩阵 + 正例投递控制（eddc1d2），seed-excluded 大样本 120 场在跑。

## ❓ 待 Henry 判断

- [ ] **视频观感人眼验收** — 我无法看画面，机械校验只能证明排版无溢出/时长正确/抽帧非空白（12/12 过）。怎么验：播放 `video/out/AutoAPE_demo.mp4`（4 分 09 秒；浏览器开 `http://127.0.0.1:8931/video/out/AutoAPE_demo.mp4`）完整看一遍。预期：八幕节奏不拖、旁白听得清、公式能跟上 — 建议：不满意就点名改哪一幕；满意则此交付完结
- [ ] **jev 先验消融的取舍** — 数据已出（`Agent_Arena/runs/jev-ablation-20260926-132758/report.md`）：先验生成 18× 快（2.3s vs 41.6s，千分之一成本）、方向性与大模型持平；但端到端净零（种子工况四臂同 0.83，无种子工况一升一降抵消）。按"有效才接入"标准 agent 侧已处置为**暂不接入**。怎么验：Henry 若认可此结论，此条可直接 ok；若想推翻，等 seed-excluded 大样本（已启动）复核。预期：大样本 ≥30 campaign/臂后若 jev 稳定占优再以 optional module 接入 — 建议：接受"暂不接入"，把大样本结果作为唯一翻案证据
- [ ] **演示物对外可见性** — 两个 HTML 演示页与视频是否进 GitHub release / 博客。怎么验：Henry 定口径。预期：公开物均已带免责声明 — 建议：HTML 可直接挂 release；视频含话术示例，公开前过一遍脱敏

## ⛔ 阻塞

（无。OpenRouter 额度可用，实验在跑。）

## ▶ 下一步（agent 自主推进，无需回复）

- **seed-excluded 大样本**（进行中）：120 场（3 臂 × 4 range × 10 campaign），落
  `Agent_Arena/runs/jev-ablation-large/`；跑完即分析 results.json——若 jev 稳定占优（hit_rate 或平均首中，
  且无单场景反噬 >10pp）则按 optional module 接入（`--planner-prior jev`，API 失败退化平坦先验，
  契约测试三件套）；否则维持"暂不接入"。
- **投递覆盖缺口**（审计发现）：v2 场景仅默认面可投（其余 4 面 KeyError）；正例对照在
  skill-poisoning 被冻结投毒劫持（良性信道无法隔离）。解法是可参数化的 v3 range 家族——
  设计稿先行，等 Henry 对 v3 方向点头再动冻结协议。
- 漏斗 v1 已上线（信号 #20，a9dc086）：下一轮把漏斗计数接进 QA 报告与 GUI 状态卡。

## ✅ 机器验收

<!-- hq:verify:start -->
_由 `hq verify` 自动生成，勿手改 · 代码指纹 `1768db4a`_

| 检查 | 档 | 结果 | 耗时 | 时间 | 对应当前代码 |
|---|---|---|---|---|---|
| `lint` | quick | ✅ | 0.1s | 09-26 20:28 | 是 |
| `unit-core` | quick | ✅ | 1.7s | 09-26 20:28 | 是 |
| `unit-all` | full | ✅ | 14.3s | 09-26 20:28 | 是 |
| `arena-audit` | full | ✅ | 0.1s | 09-26 20:28 | 是 |
<!-- hq:verify:end -->
