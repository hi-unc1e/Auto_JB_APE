import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {C, MONO, fade, rise, sceneShell} from '../theme';
import {Kicker, SceneTitle, Watermark} from '../components/Tex';

const at = (t, when) => Math.min(Math.max(t - when, 0), 1);

const STAGES = [
  {n: '规划', en: 'PLAN', c: C.indigo, bg: C.indigoBg, note: '挑一种攻击思路'},
  {n: '提交', en: 'SUBMIT', c: C.teal, bg: C.tealBg, note: '发给目标 Agent'},
  {n: '判定', en: 'JUDGE', c: C.hit, bg: C.hitBg, note: '有没有越界？'},
  {n: '变异', en: 'MUTATE', c: C.violet, bg: C.violetBg, note: '按失败原因改造话术'},
  {n: '学习', en: 'LEARN', c: C.ok, bg: C.okBg, note: '胜负写进记忆'},
];

// S3 — the high-level APE loop: plan → submit → judge → mutate → learn.
export const S3 = ({dur}) => {
  const f = useCurrentFrame();
  const t = f / 30;
  const loopLen = 4.4;
  const loopsDone = Math.max(0, Math.floor((t - 2) / loopLen));
  const active = t < 2 ? -1 : Math.floor(((t - 2) % loopLen) / loopLen * 5);
  return (
    <AbsoluteFill style={{...sceneShell, padding: '54px 64px'}}>
      <Kicker>03 · 高层循环</Kicker>
      <div style={{marginTop: 10, opacity: fade(f, 4), ...rise(f, 4)}}>
        <SceneTitle sub="一轮几秒，一夜几千次。">APE：自动提示工程</SceneTitle>
      </div>

      <div style={{position: 'relative', width: 1150, height: 400, marginTop: 20}}>
        {/* loop-back arc */}
        <svg width="1150" height="120" style={{position: 'absolute', left: 0, top: 230}}>
          <path
            d="M 1060 10 C 1060 90, 90 90, 90 14"
            fill="none"
            stroke={C.violet}
            strokeWidth={2}
            strokeDasharray="6 5"
            opacity={0.75}
          />
          <text x="575" y="86" textAnchor="middle" fontSize="15" fill={C.violet} fontFamily={MONO}>
            学习结果改变下一轮的规划
          </text>
        </svg>

        <div style={{display: 'flex', gap: 16}}>
          {STAGES.map((s, i) => {
            const o = at(t, 2 + i * 0.5);
            const isActive = active === i;
            return (
              <div
                key={s.en}
                style={{
                  flex: 1,
                  opacity: o,
                  background: isActive ? s.bg : C.panel,
                  border: `1.5px solid ${isActive ? s.c : C.line}`,
                  borderRadius: 12,
                  padding: '14px 12px 12px',
                  transform: `translateY(${isActive ? -6 : 0}px)`,
                  boxShadow: isActive ? `0 10px 24px -16px ${s.c}` : 'none',
                }}
              >
                <div style={{fontFamily: MONO, fontSize: 11, color: C.ink3, letterSpacing: '0.1em'}}>
                  {String(i + 1).padStart(2, '0')} · {s.en}
                </div>
                <div style={{fontSize: 24, fontWeight: 700, color: isActive ? s.c : C.ink, margin: '4px 0 6px'}}>
                  {s.n}
                </div>
                <div style={{fontSize: 13.5, color: C.ink2, lineHeight: 1.5}}>{s.note}</div>
                {i < 4 ? (
                  <div style={{position: 'absolute'}} />
                ) : null}
              </div>
            );
          })}
        </div>

        {/* verdict ticker under JUDGE */}
        <div
          style={{
            marginTop: 22,
            fontFamily: MONO,
            fontSize: 15,
            color: C.ink2,
            opacity: fade(f, 3 * 30),
            display: 'flex',
            gap: 8,
            alignItems: 'center',
          }}
        >
          <span style={{color: C.tealDeep}}>第 {loopsDone + 1} 轮</span>
          <span>预算 {Math.min(100, 12 + loopsDone * 7)}/100</span>
          {Array.from({length: Math.min(loopsDone + 1, 8)}).map((_, i) => (
            <span key={i} style={{color: [0, 0, 1, 0, 1, 1, 2, 1][i] === 2 ? C.fail : ([0, 0, 1, 0, 1, 1, 2, 1][i] === 1 ? C.ok : C.ink3)}}>
              {['✗', '✗', '✓', '✗', '✓', '✓', '✗', '✓'][i]}
            </span>
          ))}
          <span style={{color: C.ink3}}>判定全程机器完成，无人工</span>
        </div>

        <div
          style={{
            marginTop: 26,
            fontSize: 18,
            color: C.ink2,
            opacity: fade(f, 23 * 30),
            ...rise(f, 23 * 30),
          }}
        >
          人定义「赢」的条件（正则 / 纯函数），剩下的尝试、失败、改造、记忆，全部交给框架。
        </div>
      </div>
      <Watermark frame={f} dur={dur} />
    </AbsoluteFill>
  );
};
