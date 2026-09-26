import React, {useMemo} from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import {C, MONO} from '../theme';

// KaTeX formula renderer — fonts ship inside the npm package, so rendering is offline-safe.
export const Tex = ({tex, style}) => {
  const html = useMemo(
    () => katex.renderToString(tex, {throwOnError: false, displayMode: true}),
    [tex],
  );
  return <div style={style} dangerouslySetInnerHTML={{__html: html}} />;
};

// Small rounded label, e.g. "01 · 开场".
export const Kicker = ({children, style}) => (
  <div
    style={{
      display: 'inline-block',
      fontSize: 15,
      fontWeight: 600,
      letterSpacing: '0.12em',
      color: C.tealDeep,
      background: C.tealBg,
      border: '1px solid #CBE2EA',
      borderRadius: 999,
      padding: '5px 14px',
      ...style,
    }}
  >
    {children}
  </div>
);

export const SceneTitle = ({children, sub, style}) => (
  <div style={style}>
    <div style={{fontSize: 40, fontWeight: 700, letterSpacing: '-0.01em', color: C.ink}}>
      {children}
    </div>
    {sub ? <div style={{fontSize: 18, color: C.ink2, marginTop: 6}}>{sub}</div> : null}
  </div>
);

export const Watermark = ({frame, dur}) => (
  <div
    style={{
      position: 'absolute',
      right: 28,
      bottom: 20,
      fontFamily: MONO,
      fontSize: 13,
      color: C.ink3,
    }}
  >
    Auto APE · 授权红队研究
    <div
      style={{
        position: 'absolute',
        left: 0,
        bottom: -8,
        height: 2,
        width: `${(frame / Math.max(dur, 1)) * 100}%`,
        background: `linear-gradient(90deg, ${C.teal}, ${C.violet})`,
      }}
    />
  </div>
);
