import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {C, MONO, fade, rise, sceneShell} from '../theme';
import {Kicker, SceneTitle, Watermark} from '../components/Tex';

const at = (t, when) => Math.min(Math.max(t - when, 0), 1);

const STATS = [
  {v: '15 / 15', k: '场景全达标', note: '门槛：5 次尝试 ≥2 次命中', at: 2},
  {v: '42% → 56%', k: '种子自我进化', note: '赢家话术固化，下次开局即用', at: 8},
  {v: '75 轮 · 9.3 分钟', k: '并发 + 早停', note: '单格重跑 23 秒', at: 12},
  {v: '0 人工判定', k: '纯函数 oracle', note: '一条命令机械复核全部结论', at: 16},
];

// S8 — results, the ethics boundary, and the closing line.
export const S8 = ({dur}) => {
  const f = useCurrentFrame();
  const t = f / 30;
  const closing = at(t, 24);
  return (
    <AbsoluteFill style={{...sceneShell, padding: '54px 64px'}}>
      <Kicker>08 · 结果与边界</Kicker>
      <div style={{marginTop: 10, opacity: fade(f, 4), ...rise(f, 4)}}>
        <SceneTitle sub="在本地冻结靶场（mock 工具 + 二元 oracle）上验证。">先找到，先修好</SceneTitle>
      </div>

      <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginTop: 22, width: 860}}>
        {STATS.map((s) => {
          const o = at(t, s.at);
          return (
            <div
              key={s.k}
              style={{
                background: C.panel,
                border: `1px solid ${C.line}`,
                borderRadius: 12,
                padding: '16px 20px',
                opacity: o,
                transform: `translateY(${(1 - o) * 16}px)`,
                boxShadow: '0 10px 28px -20px rgba(16,32,58,.25)',
              }}
            >
              <div style={{fontSize: 15, color: C.ink3, fontFamily: MONO}}>{s.k}</div>
              <div style={{fontSize: 30, fontWeight: 700, color: C.tealDeep, margin: '4px 0'}}>{s.v}</div>
              <div style={{fontSize: 14.5, color: C.ink2}}>{s.note}</div>
            </div>
          );
        })}
      </div>

      <div
        style={{
          marginTop: 22,
          width: 860,
          background: C.hitBg,
          border: `1px solid #F0DDBB`,
          borderRadius: 10,
          padding: '12px 18px',
          fontSize: 16,
          color: C.hitInk,
          opacity: at(t, 18),
          ...rise(f, 18 * 30),
        }}
      >
        <b>边界声明：</b>授权红队工具。只在取得书面许可的目标与本地靶场上运行；所有演示数据均来自 mock 靶场。
      </div>

      <div
        style={{
          marginTop: 30,
          fontSize: 34,
          fontWeight: 700,
          color: C.ink,
          opacity: closing,
          transform: `translateY(${(1 - closing) * 14}px)`,
        }}
      >
        在坏人找到软肋之前，
        <span style={{color: C.teal}}>先找到它。</span>
      </div>
      <div style={{marginTop: 10, fontFamily: MONO, fontSize: 14, color: C.ink3, opacity: closing}}>
        Auto APE · jb_ape 引擎 + Agent_Arena 靶场 · 2026
      </div>
      <Watermark frame={f} dur={dur} />
    </AbsoluteFill>
  );
};
