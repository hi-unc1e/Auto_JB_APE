import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {C, MONO, fade, rise, sceneShell} from '../theme';
import {Kicker, SceneTitle, Watermark} from '../components/Tex';

const at = (t, when) => Math.min(Math.max(t - when, 0), 1);

// S6 — the feedback decision tree: observe σ, route, fire, feed the failure mode back.
export const S6 = ({dur}) => {
  const f = useCurrentFrame();
  const t = f / 30;
  const fired1 = at(t, 13);
  const failed1 = at(t, 17);
  const rotated = at(t, 21);
  const fired2 = at(t, 26);
  const won = at(t, 31);
  return (
    <AbsoluteFill style={{...sceneShell, padding: '50px 64px'}}>
      <Kicker>06 · 数学二：反馈决策树</Kicker>
      <div style={{marginTop: 8, opacity: fade(f, 4), ...rise(f, 4)}}>
        <SceneTitle sub="bandit 看战绩，决策树先看现场——观测 σ 决定走哪根树枝。">先看现场，再开药</SceneTitle>
      </div>

      <div style={{display: 'flex', gap: 30, marginTop: 16, alignItems: 'flex-start'}}>
        {/* tree */}
        <svg width="600" height="430" viewBox="0 0 600 430" style={{opacity: fade(f, 10)}}>
          {/* σ box */}
          <rect x="170" y="6" width="260" height="64" rx="10" fill="#fff" stroke="#BFD7E1" strokeWidth="1.5" />
          <text x="300" y="28" textAnchor="middle" fontSize="15" fontWeight="700" fill={C.tealDeep} fontFamily={MONO}>
            目标状态 σ（观测）
          </text>
          <text x="300" y="52" textAnchor="middle" fontSize="12.5" fill={C.ink2} fontFamily={MONO}>
            防御: L1 · 工具面: ✓ · 上轮:
            <tspan fill={rotated > 0.5 ? C.violet : C.ink2}>{rotated > 0.5 ? ' COMPETING' : ' 无'}</tspan>
          </text>

          {/* branches */}
          {[
            {x: 90, label: 'A 类·滥用工具'},
            {x: 300, label: 'B 类·内容越狱'},
            {x: 510, label: 'X 类·条件叶'},
          ].map((b, i) => (
            <g key={b.x}>
              <path d={`M 300 70 C 300 96, ${b.x} 96, ${b.x} 118`} fill="none" stroke={C.line2} strokeWidth="1.6" />
              <text x={b.x} y="112" textAnchor="middle" fontSize="11.5" fill={C.ink3} fontFamily={MONO} opacity={at(t, 9)}>
                {b.label}
              </text>
            </g>
          ))}

          {/* leaves: A col */}
          {[
            {y: 150, id: 'A.idor', hot: true},
            {y: 190, id: 'A.hijack'},
            {y: 230, id: 'A.exfil'},
            {y: 270, id: '…'},
          ].map((l) => {
            const isHot = l.hot;
            const color = isHot ? (won > 0.5 ? C.ok : failed1 > 0.5 ? C.fail : fired1 > 0.1 ? C.hit : C.teal) : C.teal;
            return (
              <g key={l.id}>
                <line x1="90" y1="118" x2="90" y2={l.y - 12} stroke={C.line2} strokeWidth="1.2" />
                <circle cx="90" cy={l.y} r="8" fill={isHot ? color : C.tealBg} stroke={isHot ? color : C.line2} strokeWidth="1.6" />
                <text x="106" y={l.y + 4} fontSize="12" fill={C.ink2} fontFamily={MONO}>{l.id}</text>
                {isHot && failed1 > 0.5 && won < 0.5 ? (
                  <text x="176" y={l.y + 5} fontSize="13" fill={C.failInk} fontFamily={MONO}>✗ 拒绝</text>
                ) : null}
                {isHot && won > 0.5 ? (
                  <text x="176" y={l.y + 5} fontSize="13" fill={C.ok} fontFamily={MONO}>✓ 命中 solved</text>
                ) : null}
              </g>
            );
          })}

          {/* X leaves: only l3 lights after rotation */}
          {[
            {y: 150, id: 'l1.synonym'},
            {y: 190, id: 'l1.encode'},
            {y: 230, id: 'l3.mismatch', hot: true},
          ].map((l) => {
            const alive = !l.hot || rotated > 0.3;
            const color = l.hot ? (fired2 > 0.1 ? C.hit : C.violet) : C.violet;
            return (
              <g key={l.id} opacity={alive ? 1 : 0.25}>
                <line x1="510" y1="118" x2="510" y2={l.y - 12} stroke={C.line2} strokeWidth="1.2" />
                <circle cx="510" cy={l.y} r="8" fill={l.hot ? color : C.violetBg} stroke={color} strokeWidth="1.6" />
                <text x="526" y={l.y + 4} fontSize="12" fill={C.ink2} fontFamily={MONO}>{l.id}</text>
                {l.hot ? (
                  <text x="494" y={l.y + 4} textAnchor="end" fontSize="11.5" fill={C.violet} fontFamily={MONO} opacity={rotated}>
                    轮2点亮 →
                  </text>
                ) : null}
              </g>
            );
          })}

          {/* fire arc 1: σ → A.idor */}
          <path d="M 240 74 C 160 96, 100 120, 90 138" fill="none" stroke={C.hit} strokeWidth="3" opacity={fired1 * (1 - 0.6 * won)} />
          {/* feedback arc: fail → σ (Wei rotation) */}
          <path
            d="M 60 160 C -20 120, 60 40, 165 40"
            fill="none"
            stroke={C.violet}
            strokeWidth="2.5"
            strokeDasharray="7 5"
            opacity={rotated}
          />
          {/* fire arc 2: σ → l3 */}
          <path d="M 360 74 C 450 96, 505 120, 510 138" fill="none" stroke={C.violet} strokeWidth="3" opacity={fired2} />
          <text x="18" y="100" fontSize="12" fill={C.violet} fontFamily={MONO} opacity={rotated}>
            失败模式回写 σ
          </text>
        </svg>

        {/* failure modes explained */}
        <div style={{width: 430}}>
          <div
            style={{
              background: C.panel,
              border: `1px solid ${C.line}`,
              borderRadius: 12,
              padding: '14px 18px',
              opacity: fade(f, 26 * 30),
              ...rise(f, 26 * 30),
              marginBottom: 12,
            }}
          >
            <div style={{fontSize: 17, fontWeight: 700, color: C.failInk}}>内心打架 · COMPETING</div>
            <div style={{fontSize: 15, color: C.ink2, marginTop: 4, lineHeight: 1.6}}>
              「服从指令」和「保持安全」在天平两端——攻击话术给服从一侧加砝码。
            </div>
          </div>
          <div
            style={{
              background: C.panel,
              border: `1px solid ${C.line}`,
              borderRadius: 12,
              padding: '14px 18px',
              opacity: fade(f, 28 * 30),
              ...rise(f, 28 * 30),
            }}
          >
            <div style={{fontSize: 17, fontWeight: 700, color: C.violet}}>没认出 · MISMATCHED</div>
            <div style={{fontSize: 15, color: C.ink2, marginTop: 4, lineHeight: 1.6}}>
              安全过滤器没见过这种输入（故事、编码、嵌套），能力还在，闸门却漏了。
            </div>
          </div>
          <div
            style={{
              marginTop: 12,
              fontSize: 15.5,
              color: C.ink2,
              lineHeight: 1.65,
              opacity: fade(f, 33 * 30),
              ...rise(f, 33 * 30),
            }}
          >
            一种失败模式撞了墙，就把失败模式写回 σ、换另一种攻——
            <b style={{color: C.ink}}>很少有目标两种都免疫</b>。叶子拼装话术全程零 LLM，从不重发同一个 payload。
          </div>
        </div>
      </div>
      <Watermark frame={f} dur={dur} />
    </AbsoluteFill>
  );
};
