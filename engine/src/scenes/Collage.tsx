import React from 'react';
import {AbsoluteFill, Img, Loop, OffthreadVideo, useVideoConfig} from 'remotion';
import {BlueprintGrid, Brackets, mono} from '../components/Brand';
import {appear, asset, clamp, easeOut, gentle, useTheme, useTime, useUnit} from '../lib';
import type {CollageItem, CollageScene as CollageSceneT} from '../types';

/*
 * Документальный коллаж: несколько кадров на одном экране.
 *   mosaic — один большой кадр и два поменьше (как полосы журнала)
 *   split  — 2–3 вертикальные панели
 *   board  — «доска расследования»: фото в белых рамках с бирками, появляются по очереди
 * Кадры открываются в моменты, привязанные к словам рассказчика (item.at).
 */

const Media: React.FC<{item: CollageItem; from: number; to: number; zoom?: number}> = ({item, from, to, zoom = 0.06}) => {
	const t = useTime();
	const theme = useTheme();
	const {fps} = useVideoConfig();
	const p = gentle(clamp((t - from) / Math.max(0.01, to - from)));
	const style: React.CSSProperties = {width: '100%', height: '100%', objectFit: 'cover', filter: theme.grade, transform: `scale(${1.02 + zoom * p})`};
	if (item.mediaType === 'video') {
		const v = <OffthreadVideo src={asset(item.src)} muted style={style} />;
		const need = to - from;
		return item.duration && item.duration < need ? <Loop durationInFrames={Math.max(1, Math.floor(item.duration * fps))}>{v}</Loop> : v;
	}
	return <Img src={asset(item.src)} style={style} />;
};

const Tag: React.FC<{text?: string; k: number}> = ({text, k}) => {
	const theme = useTheme();
	const u = useUnit();
	if (!text) return null;
	return (
		<div
			style={{
				position: 'absolute',
				left: 14 * u,
				top: 14 * u,
				fontFamily: mono(theme),
				fontSize: 17 * u,
				letterSpacing: 1.5 * u,
				color: 'rgba(242,245,247,0.85)',
				background: 'rgba(8,12,15,0.6)',
				padding: `${5 * u}px ${10 * u}px`,
				opacity: k,
				maxWidth: '90%',
			}}
		>
			{text}
		</div>
	);
};

const tagOf = (it: CollageItem) => [it.badge?.label, it.badge?.source].filter(Boolean).join(' · ') || undefined;

const Mosaic: React.FC<{scene: CollageSceneT}> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const boxes = [
		{x: 80, y: 80, w: 1100, h: 920},
		{x: 1210, y: 80, w: 630, h: 445},
		{x: 1210, y: 555, w: 630, h: 445},
	];
	const items = scene.items.slice(0, 3);
	const latest = items.reduce((acc, it, i) => (t >= (it.at ?? scene.start) ? i : acc), 0);
	return (
		<>
			{items.map((it, i) => {
				const b = boxes[i];
				const at = it.at ?? scene.start;
				const k = easeOut(clamp((t - at) / 0.6));
				if (k <= 0) return null;
				return (
					<div
						key={i}
						style={{
							position: 'absolute',
							left: b.x * u,
							top: b.y * u,
							width: b.w * u,
							height: b.h * u,
							clipPath: `inset(${(1 - k) * 100}% 0 0 0)`,
							filter: i === latest || items.length < 2 ? 'none' : 'brightness(0.72)',
						}}
					>
						<div style={{position: 'absolute', inset: 0, overflow: 'hidden', transform: `scale(${1.06 - 0.06 * k})`}}>
							<Media item={it} from={at} to={scene.end} />
						</div>
						<Brackets k={appear(t, at + 0.5, 0.7)} size={34} thickness={3} inset={-8} />
						<Tag text={tagOf(it)} k={appear(t, at + 0.8, 0.6)} />
					</div>
				);
			})}
		</>
	);
};

const Split: React.FC<{scene: CollageSceneT}> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const items = scene.items.slice(0, 3);
	const n = items.length;
	const gap = 12;
	const W = (1920 - gap * (n + 1)) / n;
	return (
		<>
			{items.map((it, i) => {
				const at = it.at ?? scene.start;
				const k = easeOut(clamp((t - at) / 0.6));
				if (k <= 0) return null;
				const x = gap + i * (W + gap);
				return (
					<div
						key={i}
						style={{
							position: 'absolute',
							left: x * u,
							top: gap * u,
							width: W * u,
							height: (1080 - gap * 2) * u,
							clipPath: `inset(0 ${(1 - k) * 100}% 0 0)`,
							overflow: 'hidden',
						}}
					>
						<Media item={it} from={at} to={scene.end} zoom={0.08} />
						<div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: 4 * u, background: theme.accent, opacity: i ? 0.9 : 0}} />
						<Tag text={tagOf(it)} k={appear(t, at + 0.8, 0.6)} />
					</div>
				);
			})}
		</>
	);
};

const Board: React.FC<{scene: CollageSceneT}> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const items = scene.items.slice(0, 4);
		// раскладка держится выше субтитров
	const spots =
		items.length === 3
			? [
					{x: 600, y: 300, r: -4},
					{x: 1330, y: 290, r: 3},
					{x: 960, y: 610, r: 2},
				]
			: [
					{x: 590, y: 290, r: -4},
					{x: 1340, y: 280, r: 3},
					{x: 720, y: 620, r: 2.5},
					{x: 1380, y: 630, r: -3},
				];
	const W = 640;
	const H = 390;
	return (
		<>
			{items.map((it, i) => {
				const at = it.at ?? scene.start;
				const k = easeOut(clamp((t - at) / 0.6));
				if (k <= 0) return null;
				const sp = spots[i];
				const isLast = i === items.reduce((acc, x, j) => (t >= (x.at ?? scene.start) ? j : acc), 0);
				const sc = (1.25 - 0.25 * k) * (isLast ? 1.04 : 0.96);
				return (
					<div
						key={i}
						style={{
							position: 'absolute',
							left: (sp.x - W / 2 - 14) * u,
							top: (sp.y - H / 2 - 14) * u,
							width: (W + 28) * u,
							padding: `${14 * u}px ${14 * u}px ${46 * u}px`,
							background: '#ECEAE4',
							boxShadow: `0 ${18 * u}px ${50 * u}px rgba(0,0,0,0.55)`,
							transform: `rotate(${sp.r * k}deg) scale(${sc})`,
							opacity: clamp(k * 1.4),
							zIndex: isLast ? 10 : i,
						}}
					>
						<div style={{width: W * u, height: H * u, overflow: 'hidden', background: '#111'}}>
							<Media item={it} from={at} to={scene.end} zoom={0.05} />
						</div>
						<div
							style={{
								position: 'absolute',
								left: 18 * u,
								bottom: 12 * u,
								right: 18 * u,
								fontFamily: mono(theme),
								fontSize: 18 * u,
								letterSpacing: 1.5 * u,
								color: '#2A2F33',
								whiteSpace: 'nowrap',
								overflow: 'hidden',
								textOverflow: 'ellipsis',
							}}
						>
							{`№ ${String(i + 1).padStart(2, '0')}${tagOf(it) ? '  ·  ' + tagOf(it) : ''}`}
						</div>
						<div
							style={{
								position: 'absolute',
								left: '50%',
								top: -12 * u,
								width: 120 * u,
								height: 30 * u,
								marginLeft: -60 * u,
								background: 'rgba(242,165,65,0.55)',
								transform: `rotate(${-sp.r}deg)`,
							}}
						/>
					</div>
				);
			})}
		</>
	);
};

export const CollageScene: React.FC<{scene: CollageSceneT}> = ({scene}) => {
	const t = useTime();
	const theme = useTheme();
	const p = gentle(clamp((t - scene.start) / Math.max(1, scene.end - scene.start)));
	return (
		<AbsoluteFill style={{backgroundColor: theme.bg, overflow: 'hidden'}}>
			<BlueprintGrid opacity={0.8} />
			<AbsoluteFill style={{transform: `scale(${1 + 0.03 * p})`}}>
				{scene.layout === 'split' ? <Split scene={scene} /> : scene.layout === 'board' ? <Board scene={scene} /> : <Mosaic scene={scene} />}
			</AbsoluteFill>
			<AbsoluteFill style={{background: `radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,${theme.vignette}) 100%)`}} />
		</AbsoluteFill>
	);
};
