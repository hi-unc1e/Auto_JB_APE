import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {C, MONO, fade, rise, sceneShell} from '../theme';
import {Kicker, SceneTitle, Watermark} from '../components/Tex';

const at = (t, when) => Math.min(Math.max(t - when, 0), 1);

const TOOLS = [
  {name: 'get_order', x: 250, y: 150},
  {name: 'refund_order', x: 470, y: 120},
  {name: 'send_email', x: 590, y: 290},
  {name: 'read_ticket', x: 360, y: 320},
];

// S2 — anatomy: LLM brain + tool hands; the attacker whispers, doesn't hack.
export const S2 = ({dur}) => {
  const f = useCurrentFrame();
  const t = f / 30;
  return (
    <AbsoluteFill style={{...sceneShell, padding: '54px 64px'}}>
      <Kicker>02 · Agent 的构造</Kicker>
      <div style={{marginTop: 10, opacity: fade(f, 4), ...rise(f, 4)}}>
        <SceneTitle sub="攻击者不硬闯服务器——他只骗大脑。">大脑 + 双手 = 攻击面</SceneTitle>
      </div>

      <div style={{position: 'relative', width: 960, height: 470, marginTop: 8}}>
        <svg width="960" height="470" viewBox="0 0 960 470">
          {/* edges brain→tools */}
          {TOOLS.map((tool, i) => {
            const o = at(t, 8 + i * 0.8);
            return (
              <line
                key={tool.name}
                x1={480}
                y1={235}
                x2={480 + (tool.x - 480) * 0.78}
                y2={235 + (tool.y - 235) * 0.78}
                stroke={C.line2}
                strokeWidth={2}
                opacity={o * 0.9}
              />
            );
          })}

          {/* attacker poison arc into read_ticket */}
          <path
            d="M 80 90 C 180 60, 260 140, 322 300"
            fill="none"
            stroke={C.fail}
            strokeWidth={2.5}
            strokeDasharray="7 5"
            opacity={at(t, 16) * 0.9}
          />

          {/* feedback violet arc appears later to hint the loop */}
        </svg>

        {/* attacker card */}
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 20,
            width: 190,
            background: C.failBg,
            border: '1px solid #F2CFCB',
            borderRadius: 10,
            padding: '10px 14px',
            opacity: at(t, 13),
          }}
        >
          <div style={{fontFamily: MONO, fontSize: 12, color: C.failInk, fontWeight: 600}}>攻击者</div>
          <div style={{fontSize: 14, color: C.failInk, marginTop: 4}}>不碰服务器，只在工单备注里「递纸条」</div>
        </div>

        {/* brain */}
        <div
          style={{
            position: 'absolute',
            left: 390,
            top: 185,
            width: 180,
            height: 100,
            borderRadius: 16,
            background: `linear-gradient(135deg, ${C.tealBg}, #fff)`,
            border: `2px solid ${C.teal}`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            opacity: at(t, 4),
            boxShadow: `0 0 ${20 + 6 * Math.sin(t * 2)}px rgba(14,116,144,.25)`,
          }}
        >
          <div style={{fontSize: 21, fontWeight: 700, color: C.tealDeep}}>LLM 大脑</div>
          <div style={{fontSize: 13, color: C.ink2}}>理解指令 · 做决定</div>
        </div>

        {/* tools */}
        {TOOLS.map((tool, i) => {
          const o = at(t, 8 + i * 0.8);
          const poisoned = tool.name === 'read_ticket' && at(t, 16) > 0;
          const highlighted = tool.name === 'get_order' && at(t, 21) > 0;
          return (
            <div
              key={tool.name}
              style={{
                position: 'absolute',
                left: tool.x,
                top: tool.y,
                opacity: o,
                fontFamily: MONO,
                fontSize: 14.5,
                padding: '7px 12px',
                borderRadius: 9,
                background: poisoned ? C.failBg : highlighted ? C.hitBg : C.panel,
                border: `1.5px solid ${poisoned ? C.fail : highlighted ? C.hit : C.line2}`,
                color: poisoned ? C.failInk : highlighted ? C.hitInk : C.ink,
                fontWeight: highlighted ? 700 : 500,
              }}
            >
              {tool.name}
              {poisoned ? ' ← 投毒' : ''}
              {highlighted ? ' ← 越权点' : ''}
            </div>
          );
        })}

        {/* bottom takeaway */}
        <div
          style={{
            position: 'absolute',
            left: 40,
            bottom: 6,
            width: 700,
            fontSize: 19,
            color: C.ink,
            background: C.panel,
            border: `1px solid ${C.line}`,
            borderLeft: `4px solid ${C.hit}`,
            borderRadius: 10,
            padding: '12px 18px',
            opacity: fade(f, 21 * 30),
            ...rise(f, 21 * 30),
          }}
        >
          骗过大脑，让它<b>心甘情愿地用合法双手</b>，查一张不属于你的订单。
        </div>
      </div>
      <Watermark frame={f} dur={dur} />
    </AbsoluteFill>
  );
};
