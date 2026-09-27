---
hq: 1
project: auto-jb-ape
theme: 安全研究
value: 研究
state: active
updated: 2026-09-27 08:53
---
# auto-jb-ape · 状态

> 引擎侧 414 测试全绿（信号 #20 漏斗 + #21 jev 先验已上线），master @ be3b8ec；jev 三轮消融收官：
> 大样本（120 场）零反噬、达预登记接入线，已按 optional module 接入（默认关闭）；Arena 侧
> delivery 三轴 + 正例投递控制在 eddc1d2，两个投递覆盖发现待 v3 靶场方向定夺。

## ❓ 待 Henry 判断

- [x] **视频观感人眼验收** — 我无法看画面，机械校验只能证明排版无溢出/时长正确/抽帧非空白（12/12 过）。怎么验：播放 `video/out/AutoAPE_demo.mp4`（4 分 09 秒；浏览器开 `http://127.0.0.1:8931/video/out/AutoAPE_demo.mp4`）完整看一遍。预期：八幕节奏不拖、旁白听得清、公式能跟上 — 建议：不满意就点名改哪一幕；满意则此交付完结
- [x] **jev 先验消融的取舍** — 已按预登记判据自行处置（无需回复，也可 hq ok 关闭）：三轮消融
  （72+36+120 场）显示 jev 先验在无种子冷启动工况**零反噬**、首中全面更快（0.75/3.45 → 0.82/3.10），
  已以 optional module 接入（`--planner-prior jev`，默认关闭，API 失败退化平坦先验，jb_ape be3b8ec）。
  怎么验：`jb-ape run --planner-prior jev ...`，或读 `Agent_Arena/runs/jev-ablation-large/report.md`。
  建议：生产（带种子）工况不开；新目标冷启动/无种子探索时开启
- [ ] **演示物对外可见性** — 两个 HTML 演示页与视频是否进 GitHub release / 博客。怎么验：Henry 定口径。预期：公开物均已带免责声明 — 建议：HTML 可直接挂 release；视频含话术示例，公开前过一遍脱敏

## ⛔ 阻塞

（无。OpenRouter 额度可用。）

## ▶ 下一步（agent 自主推进，无需回复）

- **投递覆盖缺口**（审计发现，唯一等方向的事）：v2 场景仅默认面可投（其余 4 面 KeyError）；
  正例对照在 skill-poisoning 被冻结投毒劫持（良性信道无法隔离）。解法是可参数化的 v3 range
  家族——设计稿先行，等 Henry 对 v3 方向点头再动冻结协议。
- 漏斗 v1 已上线（信号 #20）：下一轮把漏斗计数接进 QA 报告与 GUI 状态卡。
- jev 先验已上线（信号 #21）： Arena 桥（ape_bridge）下一轮暴露 planner_prior 透传。

## ✅ 机器验收

<!-- hq:verify:start -->
_由 `hq verify` 自动生成，勿手改 · 代码指纹 `6cb0b39f`_

| 检查 | 档 | 结果 | 耗时 | 时间 | 对应当前代码 |
|---|---|---|---|---|---|
| `lint` | quick | ✅ | 0.1s | 09-27 08:50 | 是 |
| `unit-core` | quick | ✅ | 1.6s | 09-27 08:50 | 是 |
| `unit-all` | full | ✅ | 14.3s | 09-26 20:28 | ⚠ 代码已变 |
| `arena-audit` | full | ✅ | 0.1s | 09-26 20:28 | ⚠ 代码已变 |
<!-- hq:verify:end -->
