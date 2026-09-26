// Shared design tokens — matches the house style of the HTML demo pages.
export const C = {
  bg1: '#F6F9FC',
  bg2: '#EDF2F9',
  panel: '#FFFFFF',
  line: '#E2E9F2',
  line2: '#D5DFEC',
  ink: '#10203A',
  ink2: '#55637B',
  ink3: '#8B99AE',
  teal: '#0E7490',
  tealBg: '#E4F1F5',
  tealDeep: '#0B5C73',
  indigo: '#4F6BD9',
  indigoBg: '#EAEEFC',
  violet: '#8B5CF6',
  violetBg: '#F1EBFE',
  hit: '#C77E12',
  hitBg: '#FDF3E1',
  hitInk: '#8A5B0B',
  fail: '#D9504B',
  failBg: '#FDECEA',
  failInk: '#A9342E',
  ok: '#1D9A6C',
  okBg: '#E3F5EE',
  dark: '#0F1B2D',
};

export const FONT = '-apple-system, "PingFang SC", "Noto Sans SC", "Hiragino Sans GB", sans-serif';
export const MONO = '"SF Mono", Menlo, Consolas, "PingFang SC", monospace';

export const fade = (frame, start = 0, dur = 12) => {
  const t = Math.min(Math.max(frame - start, 0), dur);
  return t / dur;
};

export const rise = (frame, start = 0, damp = 14) => {
  const t = Math.min(Math.max(frame - start, 0), 999);
  if (t === 0) return {transform: 'translateY(18px)', opacity: 0};
  // simple critically-damped-ish ease
  const p = 1 - Math.pow(1 - Math.min(t / damp, 1), 3);
  return {transform: `translateY(${18 * (1 - p)}px)`, opacity: p};
};

export const sceneShell = {
  background: `linear-gradient(180deg, ${C.bg1}, ${C.bg2})`,
  fontFamily: FONT,
  color: C.ink,
};
