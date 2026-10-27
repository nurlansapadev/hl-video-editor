import './fonts';
import React from 'react';
import {AbsoluteFill, Sequence, useVideoConfig} from 'remotion';
import {Background} from './components/Background';
import {Grain} from './components/Brand';
import {AudioLayer, Captions, Overlays} from './components/Layers';
import {Bars, Counter, List, Outro, Quote, TitleCard, Timeline} from './infographics/Infographics';
import {MapRoute} from './infographics/MapRoute';
import {clamp, PlanContext, SceneFromContext, setNumberLocale, useTime} from './lib';
import {CollageScene} from './scenes/Collage';
import {MediaScene} from './scenes/MediaScene';
import {enterStyle, exitStyle, transitionDuration} from './scenes/transitions';
import {defaultTheme} from './theme';
import type {Plan, Scene, Transition} from './types';

const SceneContent: React.FC<{scene: Scene; from: number; to: number}> = ({scene, from, to}) => {
	if (scene.kind === 'media') return <MediaScene scene={scene} visibleFrom={from} visibleTo={to} />;
	if (scene.kind === 'collage') return <CollageScene scene={scene} />;
	const body = (() => {
		switch (scene.kind) {
			case 'title':
				return <TitleCard scene={scene} />;
			case 'timeline':
				return <Timeline scene={scene} />;
			case 'list':
				return <List scene={scene} />;
			case 'counter':
				return <Counter scene={scene} />;
			case 'quote':
				return <Quote scene={scene} />;
			case 'map':
				return <MapRoute scene={scene} />;
			case 'bars':
				return <Bars scene={scene} />;
			case 'outro':
				return <Outro scene={scene} />;
		}
	})();
	return (
		<AbsoluteFill>
			<Background bg={scene.background} from={from} to={to} />
			{body}
		</AbsoluteFill>
	);
};

const combine = (styles: React.CSSProperties[]): React.CSSProperties => {
	const out: React.CSSProperties = {};
	const transforms: string[] = [];
	const filters: string[] = [];
	let opacity = 1;
	for (const s of styles) {
		if (s.transform) transforms.push(String(s.transform));
		if (s.filter) filters.push(String(s.filter));
		if (s.opacity !== undefined) opacity *= Number(s.opacity);
		if (s.maskImage) {
			out.maskImage = s.maskImage;
			out.WebkitMaskImage = s.WebkitMaskImage;
		}
	}
	if (transforms.length) out.transform = transforms.join(' ');
	if (filters.length) out.filter = filters.join(' ');
	if (opacity !== 1) out.opacity = opacity;
	return out;
};

const SceneWrapper: React.FC<{
	scene: Scene;
	inT: Transition;
	inWin: [number, number];
	outT: Transition | null;
	outWin: [number, number] | null;
	from: number;
	to: number;
	isLast: boolean;
	total: number;
}> = ({scene, inT, inWin, outT, outWin, from, to, isLast, total}) => {
	const t = useTime();
	const styles: React.CSSProperties[] = [];
	if (inWin[1] > inWin[0] && t < inWin[1]) styles.push(enterStyle(inT, (t - inWin[0]) / (inWin[1] - inWin[0])));
	if (outT && outWin && outWin[1] > outWin[0] && t > outWin[0]) styles.push(exitStyle(outT, (t - outWin[0]) / (outWin[1] - outWin[0])));
	if (isLast) styles.push({opacity: clamp((total - t) / 1.2)});
	return (
		<AbsoluteFill style={combine(styles)}>
			<SceneContent scene={scene} from={from} to={to} />
		</AbsoluteFill>
	);
};

export const Main: React.FC<Plan> = (plan) => {
	const {fps} = useVideoConfig();
		const theme = {...defaultTheme, ...(plan.theme ?? {})};
	setNumberLocale(plan.language);
	const scenes = [...plan.scenes].sort((a, b) => a.start - b.start);
	const defT: Transition = plan.defaultTransition ?? {type: 'fade', duration: 0.8};
	const total = plan.duration;

	return (
		<PlanContext.Provider value={{plan, theme}}>
			<AbsoluteFill style={{backgroundColor: '#000'}}>
				{scenes.map((scene, i) => {
					const inT = scene.transition ?? (i === 0 ? {type: 'fade', duration: 1.0} : defT);
					const inD = transitionDuration(inT);
					const next = scenes[i + 1];
					const outT = next ? next.transition ?? defT : null;
					const outD = transitionDuration(outT ?? undefined);
					const inWin: [number, number] = i === 0 ? [scene.start, scene.start + inD] : [scene.start - inD / 2, scene.start + inD / 2];
					const outWin: [number, number] | null = next ? [next.start - outD / 2, next.start + outD / 2] : null;
					const from = Math.max(0, inWin[0]);
					const to = Math.min(total, outWin ? Math.max(outWin[1], scene.end) : scene.end);
					const fromF = Math.round(from * fps);
					const dur = Math.max(1, Math.round(to * fps) - fromF);
					return (
						<Sequence key={scene.id ?? i} from={fromF} durationInFrames={dur} premountFor={Math.round(fps * 1.5)} name={`${scene.id} · ${scene.kind}`}>
							<SceneFromContext.Provider value={fromF}>
								<SceneWrapper
									scene={scene}
									inT={inT}
									inWin={inWin}
									outT={outT}
									outWin={outWin}
									from={from}
									to={to}
									isLast={!next}
									total={total}
								/>
							</SceneFromContext.Provider>
						</Sequence>
					);
				})}
				{theme.style !== 'cartoon' ? <Grain amount={theme.grain ?? 0.06} /> : null}
				<Overlays overlays={scenes.flatMap((s) => s.overlays ?? [])} />
				{plan.captions?.enabled ? <Captions cues={plan.captions.cues} scenes={scenes} /> : null}
				<AudioLayer />
			</AbsoluteFill>
		</PlanContext.Provider>
	);
};
