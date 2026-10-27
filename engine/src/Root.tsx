import React from 'react';
import {Composition} from 'remotion';
import demo from './demo-plan.json';
import {Main} from './Main';
import type {Plan} from './types';

export const Root: React.FC = () => (
	<Composition
		id="Main"
		component={Main}
		defaultProps={demo as unknown as Plan}
		fps={30}
		width={1920}
		height={1080}
		durationInFrames={300}
		calculateMetadata={({props}) => ({
			fps: props.fps,
			width: props.width,
			height: props.height,
			durationInFrames: Math.max(1, Math.ceil(props.duration * props.fps)),
		})}
	/>
);
