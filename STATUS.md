---
hq: 1
project: auto-jb-ape
theme: 安全研究
value: 研究
state: active
updated: 2026-10-07 20:08
---
# auto-jb-ape · 状态

> 本轮 P0/P1 已实现：Arena v3.1 五信道可读取，15×5 离线正例对照通过；
> `injection` × `mistralai/ministral-8b-2512` 的五信道真实模型正例对照通过（仅证明该抽样下可投递）。
> JB_APE 研究卡、来源快照、同候选/同投递面严格证据门槛与侦察→决策树接线已落地；
> 423 项严格离线测试及 HQ full 4/4 通过。跨仓库晋升链路用脚本化目标验过，尚无新论文手法的真实模型 ASR 结论。

## ❓ 待 Henry 判断

- [x] **视频观感人眼验收** — 我无法看画面，机械校验只能证明排版无溢出/时长正确/抽帧非空白（12/12 过）。怎么验：播放 `video/out/AutoAPE_demo.mp4`（4 分 09 秒；浏览器开 `http://127.0.0.1:8931/video/out/AutoAPE_demo.mp4`）完整看一遍。预期：八幕节奏不拖、旁白听得清、公式能跟上 — 建议：不满意就点名改哪一幕；满意则此交付完结
- [x] **jev 先验消融的取舍** — 已按预登记判据自行处置（无需回复，也可 hq ok 关闭）：三轮消融
  （72+36+120 场）显示 jev 先验在无种子冷启动工况**零反噬**、首中全面更快（0.75/3.45 → 0.82/3.10），
  已以 optional module 接入（`--planner-prior jev`，默认关闭，API 失败退化平坦先验，jb_ape be3b8ec）。
  怎么验：`jb-ape run --planner-prior jev ...`，或读 `Agent_Arena/runs/jev-ablation-large/report.md`。
  建议：生产（带种子）工况不开；新目标冷启动/无种子探索时开启
- [x] **演示物对外可见性** — 两个 HTML 演示页与视频是否进 GitHub release / 博客。怎么验：Henry 定口径。预期：公开物均已带免责声明 — 建议：HTML 可直接挂 release；视频含话术示例，公开前过一遍脱敏 → Henry: 暂不主动曝光：演示物（两个 HTML + 视频）随仓库自然可见即可，不做 release 附件、不进 README 演示区、不发博客。
- [x] **v3 靶场方向** — Henry 已拍板（2026-09-27），v3.1 已完成：**参数化 v3 家族**——5 投递面全参数化
  （每面独立毒内容语义）+ 独立良性信道（正例对照全矩阵有效）；v1/v2 冻结定义未改。
  旧 manifest 仍须在对应源码版本复核，不能直接套当前源码指纹。

## ⛔ 阻塞

（无。OpenRouter 额度可用。）

## ▶ 下一步（agent 自主推进，无需回复）

- **P2：选一篇具体论文或博客做前瞻性研究卡**：按 `RESEARCH_SOP.md` 保存原文与候选，
  在 Arena 预登记模型、信道、预算、正例/未送达对照和旧种子排除实验；没有本地证据前只保留知识卡。
- 漏斗 v1 已上线（信号 #20）：下一轮把漏斗计数接进 QA 报告与 GUI 状态卡。
- jev 先验已上线（信号 #21）： Arena 桥（ape_bridge）下一轮暴露 planner_prior 透传。

## ✅ 机器验收

<!-- hq:verify:start -->
_由 `hq verify` 自动生成，勿手改 · 代码指纹 `b20d1f0d`_

| 检查 | 档 | 结果 | 耗时 | 时间 | 对应当前代码 |
|---|---|---|---|---|---|
| `lint` | quick | ✅ | 0.1s | 10-07 20:08 | 是 |
| `unit-core` | quick | ✅ | 1.7s | 10-07 20:08 | 是 |
| `unit-all` | full | ✅ | 14.4s | 10-07 20:08 | 是 |
| `arena-audit` | full | ✅ | 0.2s | 10-07 20:08 | 是 |
<!-- hq:verify:end -->
