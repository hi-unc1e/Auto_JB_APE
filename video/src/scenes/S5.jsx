import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {C, MONO, fade, rise, sceneShell} from '../theme';
import {Kicker, SceneTitle, Watermark, Tex} from '../components/Tex';

const at = (t, when) => Math.min(Math.max(t - when, 0), 1);

// Lanczos log-gamma, enough precision for plotting Beta densities.
const lgamma = (z) => {
  const g = 7;
  const cof = [
    0.99999999999980993, 676.5203681218851, -1259.1392167224028,
    771.32342877765313, -176.61502916214059, 12.507343278686905,
    -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7,
  ];
  if (z < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * z)) - lgamma(1 - z);
  z -= 1;
  let x = cof[0];
  for (let i = 1; i < g + 2; i++) x += cof[i] / (z + i);
  const tt = z + g + 0.5;
  return 0.5 * Math.log(2 * Math.PI) + (z + 0.5) * Math.log(tt) - tt + Math.log(x);
};

const betaPdf = (x, a, b) =>
  Math.exp((a - 1) * Math.log(x) + (b - 1) * Math.log(1 - x) - (lgamma(a) + lgamma(b) - lgamma(a + b)));

const betaPath = (a, b, w, h) => {
  const pts = [];
  let max = 0;
  for (let i = 1; i <= 99; i++) {
    const x = i / 100;
    const y = betaPdf(x, a, b);
    max = Math.max(max, y);
    pts.push([x, y]);
  }
  return pts.map(([x, y]) => `${(x * w).toFixed(1)},${(h - (y / max) * h * 0.92).toFixed(1)}`).join(' ');
};

const MACHINES = [
  {name: '话术 A · 权威覆盖', a: 7, b: 5},
  {name: '话术 B · 角色扮演', a: 3, b: 6},
  {name: '话术 C · 场景嵌套', a: 5, b: 5},
];

// S5 — multi-armed bandit: Beta bookkeeping + Thompson sampling.
export const S5 = ({dur}) => {
  const f = useCurrentFrame();
  const t = f / 30;
  // posterior snapshots for machine A as wins/failures accumulate
  const steps = [
    {a: 1, b: 1, label: 'Beta(1,1) 完全不知道'},
    {a: 4, b: 3, label: 'Beta(4,3) 略有偏好'},
    {a: 9, b: 5, label: 'Beta(9,5) 越试越确定'},
  ];
  const stepIdx = t < 15 ? 0 : t < 24 ? 1 : 2;
  const cur = steps[stepIdx];
  return (
    <AbsoluteFill style={{...sceneShell, padding: '50px 64px'}}>
      <Kicker>05 · 数学一：多臂老虎机</Kicker>
      <div style={{marginTop: 8, opacity: fade(f, 4), ...rise(f, 4)}}>
        <SceneTitle sub="哪种攻击思路值得下一发子弹？让概率替我们记账。">Beta 分布记账，汤普森采样翻牌</SceneTitle>
      </div>

      <div style={{display: 'flex', gap: 30, marginTop: 20, alignItems: 'flex-start'}}>
        {/* slot machines */}
        <div style={{width: 420, opacity: fade(f, 10), ...rise(f, 10)}}>
          {MACHINES.map((m, i) => {
            const mean = (m.a / (m.a + m.b)).toFixed(2);
            const active = i === 0;
            return (
              <div
                key={m.name}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  background: active ? C.tealBg : C.panel,
                  border: `1.5px solid ${active ? C.teal : C.line}`,
                  borderRadius: 10,
                  padding: '10px 14px',
                  marginBottom: 10,
                }}
              >
                <div style={{fontSize: 26}}>{active ? '🎰' : '🎰'}</div>
                <div style={{flex: 1}}>
                  <div style={{fontSize: 16, fontWeight: 600, color: C.ink}}>{m.name}</div>
                  <div style={{fontFamily: MONO, fontSize: 13, color: C.ink2}}>
                    α={m.a} 赢 · β={m.b} 输 → 估计胜率 {mean}
                  </div>
                </div>
                <div style={{width: 90, height: 8, background: C.line, borderRadius: 99, overflow: 'hidden'}}>
                  <div style={{width: `${mean * 100}%`, height: '100%', background: active ? C.teal : C.indigo}} />
                </div>
              </div>
            );
          })}
          <div style={{fontSize: 14.5, color: C.ink2, lineHeight: 1.6, marginTop: 6}}>
            中奖率未知，只能试——这就是经典的<b>多臂老虎机</b>问题。
          </div>
        </div>

        {/* formulas + evolving posterior */}
        <div style={{flex: 1}}>
          <div
            style={{
              display: 'flex',
              gap: 14,
              opacity: fade(f, 9 * 30),
              ...rise(f, 9 * 30),
            }}
          >
            <div style={{flex: 1, background: C.panel, border: `1px solid ${C.line}`, borderRadius: 10, padding: '10px 14px'}}>
              <Tex tex={String.raw`\hat{p} = \dfrac{\alpha}{\alpha + \beta}`} style={{fontSize: 16}} />
              <div style={{fontSize: 13, color: C.ink2, marginTop: 4}}>胜率估计 = 赢 ÷ 总尝试</div>
            </div>
            <div style={{flex: 1, background: C.panel, border: `1px solid ${C.line}`, borderRadius: 10, padding: '10px 14px'}}>
              <Tex tex={String.raw`\theta \sim \mathrm{Beta}(\alpha,\beta)`} style={{fontSize: 16}} />
              <div style={{fontSize: 13, color: C.ink2, marginTop: 4}}>汤普森采样：从整个分布抽一个数</div>
            </div>
          </div>

          <div
            style={{
              display: 'flex',
              gap: 14,
              marginTop: 12,
              opacity: fade(f, 22 * 30),
              ...rise(f, 22 * 30),
            }}
          >
            <div style={{flex: 1, background: C.okBg, border: `1px solid #BEE5D4`, borderRadius: 10, padding: '8px 14px', fontFamily: MONO, fontSize: 15, color: C.ok}}>
              命中 → α ← α + 1
            </div>
            <div style={{flex: 1, background: C.failBg, border: `1px solid #F2CFCB`, borderRadius: 10, padding: '8px 14px', fontFamily: MONO, fontSize: 15, color: C.failInk}}>
              失败 → β ← β + 1
            </div>
          </div>

          {/* posterior curve */}
          <div
            style={{
              marginTop: 14,
              background: C.panel,
              border: `1px solid ${C.line}`,
              borderRadius: 12,
              padding: '12px 16px 6px',
              opacity: fade(f, 15 * 30),
            }}
          >
            <div style={{fontSize: 14.5, color: C.ink}}>
              话术 A 的胜率分布：<b style={{fontFamily: MONO}}>{cur.label}</b>
            </div>
            <svg width="470" height="140" viewBox="0 0 470 140">
              <line x1="30" y1="125" x2="450" y2="125" stroke={C.line2} strokeWidth="1" />
              <line x1="30" y1="10" x2="30" y2="125" stroke={C.line2} strokeWidth="1" />
              {/* ghost curves of the other steps */}
              {steps.map((s, i) => (
                <polyline
                  key={i}
                  points={betaPath(s.a, s.b, 400, 120)}
                  fill="none"
                  stroke={i === stepIdx ? C.teal : C.line2}
                  strokeWidth={i === stepIdx ? 3 : 1.5}
                  opacity={i === stepIdx ? 1 : 0.5}
                  transform="translate(38,2)"
                />
              ))}
              <text x="445" y="138" textAnchor="end" fontSize="11" fill={C.ink3} fontFamily={MONO}>胜率 p →</text>
              <text x="34" y="12" fontSize="11" fill={C.ink3} fontFamily={MONO}>可能性</text>
            </svg>
          </div>
        </div>
      </div>

      <div
        style={{
          marginTop: 14,
          fontSize: 17,
          color: C.ink2,
          opacity: fade(f, 34 * 30),
          ...rise(f, 34 * 30),
        }}
      >
        不从平均值选、而从分布抽：胜率不确定的思路也会被「翻牌」——<b style={{color: C.ink}}>惊喜不会被埋没</b>。
      </div>
      <Watermark frame={f} dur={dur} />
    </AbsoluteFill>
  );
};
