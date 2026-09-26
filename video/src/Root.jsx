import React from 'react';
import {AbsoluteFill, Audio, Composition, Sequence, staticFile} from 'remotion';
import timings from './timings.json';
import {S1} from './scenes/S1';
import {S2} from './scenes/S2';
import {S3} from './scenes/S3';
import {S4} from './scenes/S4';
import {S5} from './scenes/S5';
import {S6} from './scenes/S6';
import {S7} from './scenes/S7';
import {S8} from './scenes/S8';
import {C, sceneShell, FONT} from './theme';

const FPS = 30;
const TAIL = 0.9; // breathing room after each narration clip, in seconds

const SCENES = {s1: S1, s2: S2, s3: S3, s4: S4, s5: S5, s6: S6, s7: S7, s8: S8};

const layout = (() => {
  let cursor = 0;
  const segs = timings.map((t) => {
    const frames = Math.ceil((t.audioDur + TAIL) * FPS);
    const seg = {...t, from: cursor, frames};
    cursor += frames;
    return seg;
  });
  return {segs, totalFrames: cursor};
})();

const Main = () => (
  <AbsoluteFill style={{...sceneShell, fontFamily: FONT, backgroundColor: C.bg1}}>
    {layout.segs.map((seg) => {
      const Scene = SCENES[seg.id];
      return (
        <Sequence key={seg.id} from={seg.from} durationInFrames={seg.frames} name={`${seg.id} (${seg.audioDur.toFixed(1)}s)`}>
          <>
            <Scene dur={seg.frames} />
            <Audio src={staticFile(seg.audio)} volume={1} />
          </>
        </Sequence>
      );
    })}
  </AbsoluteFill>
);

export const RemotionRoot = () => (
  <>
    <Composition
      id="Main"
      component={Main}
      durationInFrames={layout.totalFrames}
      fps={FPS}
      width={1280}
      height={720}
    />
  </>
);
