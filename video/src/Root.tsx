import React from 'react';
import {Composition} from 'remotion';
import {Werbevideo, GESAMT} from './Werbevideo';

export const Root: React.FC = () => (
  <Composition
    id="Werbevideo"
    component={Werbevideo}
    durationInFrames={GESAMT}
    fps={30}
    width={1920}
    height={1080}
  />
);
