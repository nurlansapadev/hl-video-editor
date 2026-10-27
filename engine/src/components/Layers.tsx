import React from 'react';
import {AbsoluteFill, Audio, Sequence, useVideoConfig} from 'remotion';
import {asset, clamp, usePlan, useTheme, useTime, useUnit, window01} from '../lib';
import type {CaptionCue, MusicTrack, Overlay, Scene} from '../types';
import {Brackets, MonoLabel, mono, Ruler} from './Brand';

// ───────────────────────── Субтитры ─────────────────────────
export const Captions: React.FC<{cues: CaptionCue[]; scenes: Scene[]}> = ({cues, scenes}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const scene = scenes.find((s) => t >= s.start && t < s.end);
	if (scene && scene.captions === false) return null;
	const cue = cues.find((c) => t >= c.start && t < c.end);
	if (!cue) return null;
	const k = window01(t, cue.start, cue.end, 0.12, 0.12);
	const hl = theme.captionHighlight;
	let wordIdx = 0;
	return (
		<AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 64 * u}}>
			<div
				style={{
					maxWidth: 1500 * u,
					padding: `${14 * u}px ${34 * u}px`,
					borderRadius: 14 * u,
					background: theme.captionBg,
					textAlign: 'center',
					opacity: k,
					transform: `translateY(${(1 - k) * 8 * u}px)`,
				}}
			>
				{cue.lines.map((line, li) => (
					<div
						key={li}
						style={{
							fontFamily: theme.bodyFont,
							fontWeight: 600,
							fontSize: theme.captionSize * u,
							lineHeight: 1.3,
							color: theme.text,
							textShadow: '0 2px 8px rgba(0,0,0,0.6)',
						}}
					>
						{hl && cue.words
							? line.split(' ').map((w, wi) => {
									const word = cue.words![wordIdx++];
									const active = word && t >= word.start && t < word.end + 0.08;
									return (
										<span key={wi} style={{color: active ? hl : undefined}}>
											{w}
											{' '}
										</span>
									);
								})
							: line}
					</div>
				))}
			</div>
		</AbsoluteFill>
	);
};

// ───────────────────────── Надписи поверх кадра ─────────────────────────
const OverlayItem: React.FC<{o: Overlay}> = ({o}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const k = window01(t, o.start, o.end, 0.6, 0.5);
	if (k <= 0) return null;
	if (theme.style !== 'cartoon') return <BrandOverlay o={o} k={k} />;
	if (o.type === 'lowerThird') {
		return (
			<AbsoluteFill style={{justifyContent: 'flex-end', paddingLeft: 110 * u, paddingBottom: 210 * u}}>
				<div style={{display: 'flex', opacity: k, transform: `translateX(${(1 - k) * -40 * u}px)`}}>
					<div style={{width: 8 * u, background: theme.accent, borderRadius: 4 * u, marginRight: 24 * u}} />
					<div style={{background: theme.panel, padding: `${18 * u}px ${34 * u}px`, borderRadius: 10 * u}}>
						<div style={{fontFamily: theme.bodyFont, fontWeight: 700, fontSize: 48 * u, color: theme.text}}>{o.title}</div>
						{o.subtitle ? (
							<div style={{fontFamily: theme.bodyFont, fontWeight: 500, fontSize: 32 * u, color: theme.muted, marginTop: 4 * u}}>
								{o.subtitle}
							</div>
						) : null}
					</div>
				</div>
			</AbsoluteFill>
		);
	}
	if (o.type === 'date') {
		return (
			<AbsoluteFill style={{padding: `${80 * u}px ${100 * u}px`}}>
				<div
					style={{
						alignSelf: 'flex-start',
						opacity: k,
						transform: `translateY(${(1 - k) * -16 * u}px)`,
						fontFamily: theme.headingFont,
						fontWeight: 700,
						fontSize: 64 * u,
						color: theme.accent,
						padding: `${8 * u}px ${30 * u}px`,
						borderBottom: `${4 * u}px solid ${theme.accent}`,
						background: 'rgba(12,10,8,0.45)',
						borderRadius: `${10 * u}px ${10 * u}px 0 0`,
					}}
				>
					{o.text}
				</div>
			</AbsoluteFill>
		);
	}
	const pos = o.position ?? 'top';
	return (
		<AbsoluteFill
			style={{
				alignItems: 'center',
				justifyContent: pos === 'top' ? 'flex-start' : pos === 'center' ? 'center' : 'flex-end',
				padding: `${110 * u}px ${120 * u}px ${230 * u}px`,
			}}
		>
			<div
				style={{
					opacity: k,
					transform: `scale(${0.95 + 0.05 * k})`,
					background: theme.panel,
					padding: `${20 * u}px ${44 * u}px`,
					borderRadius: 16 * u,
					fontFamily: theme.bodyFont,
					fontWeight: 700,
					fontSize: 56 * u,
					color: theme.text,
					textAlign: 'center',
				}}
			>
				{o.text}
			</div>
		</AbsoluteFill>
	);
};

/** Подписи в фирменном стиле «чертёж». */
const BrandOverlay: React.FC<{o: Overlay; k: number}> = ({o, k}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const draw = clamp((t - o.start - 0.15) / 0.9);
	if (o.type === 'lowerThird') {
		return (
			<AbsoluteFill style={{justifyContent: 'flex-end', paddingLeft: 110 * u, paddingBottom: 230 * u}}>
				<div style={{alignSelf: 'flex-start', position: 'relative', padding: `${22 * u}px ${36 * u}px ${20 * u}px`,
					background: 'linear-gradient(90deg, rgba(8,12,15,0.82), rgba(8,12,15,0.55))', opacity: k,
					transform: `translateX(${(1 - k) * -30 * u}px)`}}>
					<Brackets k={draw} size={22} thickness={3} />
					<div style={{fontFamily: theme.headingFont, fontWeight: 700, fontSize: 50 * u, color: theme.text, lineHeight: 1.1}}>{o.title}</div>
					{o.subtitle ? <MonoLabel text={o.subtitle} size={22} style={{marginTop: 10 * u}} /> : null}
					<div style={{marginTop: 14 * u}}>
						<Ruler k={draw} width={260} ticks={10} />
					</div>
				</div>
			</AbsoluteFill>
		);
	}
	if (o.type === 'date') {
		return (
			<AbsoluteFill style={{padding: `${70 * u}px ${90 * u}px`}}>
				<div style={{alignSelf: 'flex-start', position: 'relative', padding: `${16 * u}px ${28 * u}px`, background: 'rgba(8,12,15,0.6)',
					opacity: k, transform: `translateY(${(1 - k) * -14 * u}px)`}}>
					<Brackets k={draw} size={20} thickness={3} />
					<div style={{fontFamily: mono(theme), fontWeight: 600, fontSize: 48 * u, letterSpacing: 6 * u, color: theme.accent, textTransform: 'uppercase'}}>
						{o.text}
					</div>
				</div>
			</AbsoluteFill>
		);
	}
	const pos = o.position ?? 'top';
	return (
		<AbsoluteFill style={{alignItems: 'center', justifyContent: pos === 'top' ? 'flex-start' : pos === 'center' ? 'center' : 'flex-end',
			padding: `${110 * u}px ${120 * u}px ${230 * u}px`}}>
			<div style={{position: 'relative', opacity: k, transform: `scale(${0.97 + 0.03 * k})`, background: theme.panel,
				padding: `${22 * u}px ${46 * u}px`, fontFamily: theme.bodyFont, fontWeight: 700, fontSize: 54 * u, color: theme.text, textAlign: 'center'}}>
				<Brackets k={draw} size={24} thickness={3} />
				{o.text}
			</div>
		</AbsoluteFill>
	);
};

export const Overlays: React.FC<{overlays: Overlay[]}> = ({overlays}) => (
	<>
		{overlays.map((o, i) => (
			<OverlayItem key={i} o={o} />
		))}
	</>
);

// ───────────────────────── Звук ─────────────────────────
const duckActivity = (t: number, intervals: [number, number][], attack = 0.35, release = 0.8) => {
	let a = 0;
	for (const [s, e] of intervals) {
		if (t >= s && t <= e) return 1;
		if (t < s && t > s - attack) a = Math.max(a, 1 - (s - t) / attack);
		if (t > e && t < e + release) a = Math.max(a, 1 - (t - e) / release);
	}
	return a;
};

const Music: React.FC<{track: MusicTrack; total: number}> = ({track, total}) => {
	const {fps} = useVideoConfig();
	const start = track.start ?? 0;
	const end = track.end ?? total;
	const base = track.volume ?? 0.25;
	const duck = track.duckVolume ?? 0.07;
	const openVol = track.openVolume ?? base;
	const fadeIn = track.fadeIn ?? 1.5;
	const fadeOut = track.fadeOut ?? 3;
	return (
		<Sequence from={Math.round(start * fps)} durationInFrames={Math.max(1, Math.round((end - start) * fps))}>
			<Audio
				src={asset(track.src)}
				loop
				volume={(f) => {
					const t = start + f / fps;
					const act = track.duck ? duckActivity(t, track.duck) : 0;
					const openAct = track.open ? duckActivity(t, track.open, 1.2, 1.2) : 0;
					const free = base + (openVol - base) * openAct;
					const level = free + (duck - free) * act;
					const fade = Math.min(clamp((t - start) / fadeIn), clamp((end - t) / fadeOut));
					return level * fade;
				}}
			/>
		</Sequence>
	);
};

export const AudioLayer: React.FC = () => {
	const {plan} = usePlan();
	const {fps} = useVideoConfig();
	return (
		<>
			{plan.voice ? (
				<Sequence from={Math.round((plan.voice.offset ?? 0) * fps)}>
					<Audio src={asset(plan.voice.src)} volume={plan.voice.volume ?? 1} />
				</Sequence>
			) : null}
			{(plan.music ?? []).map((m, i) => (
				<Music key={i} track={m} total={plan.duration} />
			))}
			{(plan.sfx ?? []).map((s, i) => (
				<Sequence key={i} from={Math.max(0, Math.round(s.at * fps))} durationInFrames={Math.round(4 * fps)}>
					<Audio src={asset(s.src)} volume={s.volume ?? 0.35} />
				</Sequence>
			))}
		</>
	);
};
