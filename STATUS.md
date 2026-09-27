---
hq: 1
project: auto-jb-ape
theme: 安全研究
value: 研究
state: active
updated: 2026-09-27 09:11
---
# auto-jb-ape · 状态

> 引擎侧 414 测试全绿（信号 #20 漏斗 + #21 jev 先验已上线），master @ 0831f0e（README 双语亮点已推送）；jev 三轮消融收官：
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
- [x] **v3 靶场方向** — Henry 已拍板（2026-09-27）：**参数化 v3 家族**——5 投递面全参数化
  （每面独立毒内容语义）+ 独立良性信道（正例对照全矩阵有效）；v1/v2 字节不动，历史数据可比。
  执行中，见 ▶。

## ⛔ 阻塞

（无。OpenRouter 额度可用。）

## ▶ 下一步（agent 自主推进，无需回复）

- **参数化 v3 家族（已批准，v3.0 已落地）**：Arena `2f8f7ff`——8 个 user_prompt 原生场景补齐
  5 面投递元数据（全 15 场景 × 5 面可放置）；良性 artifact 在信道内原位替换冻结毒 +
  `suppress_legacy_untrusted` 隔离开关，正例对照不再被劫持（skill-poisoning user_prompt 对照
  从 oracle_success 劫持 → ✅）。v1/v2 注册表字节冻结（sha256 守卫）。
  **v3.1 待办**：其余 4 面在会话流程中尚未暴露（矩阵已精确归因"channel not exercised by
  session flow"）——需要 handler 层的面暴露工作，改动仅在新 extra 键下生效。
- 漏斗 v1 已上线（信号 #20）：下一轮把漏斗计数接进 QA 报告与 GUI 状态卡。
- jev 先验已上线（信号 #21）： Arena 桥（ape_bridge）下一轮暴露 planner_prior 透传。

## ✅ 机器验收

<!-- hq:verify:start -->
_由 `hq verify` 自动生成，勿手改 · 代码指纹 `5fcdc47a`_

| 检查 | 档 | 结果 | 耗时 | 时间 | 对应当前代码 |
|---|---|---|---|---|---|
| `lint` | quick | ✅ | 0.1s | 09-27 09:11 | 是 |
| `unit-core` | quick | ✅ | 1.6s | 09-27 09:11 | 是 |
| `unit-all` | full | ✅ | 14.3s | 09-26 20:28 | ⚠ 代码已变 |
| `arena-audit` | full | ✅ | 0.1s | 09-26 20:28 | ⚠ 代码已变 |
<!-- hq:verify:end -->
