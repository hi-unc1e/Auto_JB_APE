# Auto APE 演示视频（Remotion）

一支 4 分 09 秒的科普短片：Auto APE 框架如何做 **AI Agent 授权红队测试**。
面向高中生可懂的讲解，同时覆盖高层循环（plan → submit → judge → mutate → learn）、
反馈决策树（σ 观测 / 路由 / Wei 失败模式轮换）与三个数学点
（Beta-汤普森采样、二元 oracle、困惑度 PPL）。

- 成片：`out/AutoAPE_demo.mp4`（1280×720 · 30fps · 4:09 · ~14 MB；不入库）
- 旁白：edge-tts `zh-CN-YunxiNeural`，逐幕音频在 `public/*.mp3`（不入库）
- 公式：KaTeX（字体随 npm 包分发，渲染离线可用）

## 再生步骤

```bash
cd video
npm install                                   # Remotion 4 + React 18 + KaTeX
python3 narration/make_tts.py                 # 重新合成旁白并生成 src/timings.json
npx remotion render src/index.js Main out/AutoAPE_demo.mp4
python3 scripts/verify_video.py               # 机械校验：时长/音轨/抽帧/动画推进
```

## 结构

| 文件 | 作用 |
|---|---|
| `src/Root.jsx` | 组合 `Main`：按 timings 逐幕排 Sequence + 挂旁白 |
| `src/theme.js` | 房子风格配色（与 ape_iteration_demo.html 一致的浅色系） |
| `src/components/Tex.jsx` | KaTeX 渲染器 + Kicker/标题/水印 |
| `src/scenes/S1..S8.jsx` | 八幕：开场钩子 / Agent 构造 / APE 循环 / oracle / 老虎机数学 / 决策树 / PPL / 结果与边界 |
| `narration/script.json` | 旁白全文（改文案从这里开始） |

注：此版本 `remotion` 包未导出 `OffthreadAudio`，用 `<Audio>` 即可（v4 渲染管线本就离线提取音频）。

## 授权边界

视频内容仅演示**本地冻结靶场**（mock 工具 + 二元 oracle）上的授权测试；片尾含边界声明。
