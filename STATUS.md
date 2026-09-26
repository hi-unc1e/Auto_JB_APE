---
hq: 1
project: auto-jb-ape
theme: 安全研究
value: 研究
state: active
updated: 2026-09-26 20:33
---
# auto-jb-ape · 状态

> 引擎侧（jb_ape）393 测试全绿、ruff 干净，master @ ef8953e（Remotion 科普视频已提交）；
> 靶场侧 15 场景双分母 ASR 硬指标 15/15 机械审计通过（Agent_Arena @ c34c729，未推送）。

## ❓ 待 Henry 判断

- [ ] **视频观感人眼验收** — 我无法看画面，机械校验只能证明排版无溢出/时长正确/抽帧非空白（12/12 过）。怎么验：播放 `video/out/AutoAPE_demo.mp4`（4 分 09 秒；浏览器开 `http://127.0.0.1:8931/video/out/AutoAPE_demo.mp4`）完整看一遍。预期：八幕节奏不拖、旁白听得清、公式能跟上 — 建议：不满意就点名改哪一幕；满意则此交付完结
- [ ] **jev 先验消融的取舍**（实验跑完后判断）— 怎么验：看 `Agent_Arena/runs/jev-ablation-*/report.md` 四臂对照（rounds-to-first-hit / 命中率 / 先验生成时延成本）。预期：jev 先验仅在命中更快的场景成立、且 API 失败可退化 — 建议：只在"优势 ≥1 次提交且不劣化任何场景"时合入 bandit warm-start，强度取弱档
- [ ] **演示物对外可见性** — 两个 HTML 演示页与视频是否进 GitHub release / 博客。怎么验：Henry 定口径。预期：公开物均已带免责声明 — 建议：HTML 可直接挂 release；视频含话术示例，公开前过一遍脱敏

## ⛔ 阻塞

（无。OpenRouter 额度可用，实验在跑。）

## ▶ 下一步（agent 自主推进，无需回复）

- jev 消融实验：写完 `experiments/jev_prior_ablation.py` → 烟雾（1 range × 2 campaign × 4 臂）
  → 全量后台（4 臂 × 8 range × 5 campaign，预算 6）→ 出 report.md 并把结论写回本 STATUS。
- 实验脚本与 hq 三件套入库（master，pre-commit 三道门）。

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
