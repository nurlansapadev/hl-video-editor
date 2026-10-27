import React from 'react';
import {AbsoluteFill, Img, Loop, OffthreadVideo, useVideoConfig} from 'remotion';
import {asset, clamp, gentle, smooth, useTheme, useTime} from '../lib';
import type {Framing, MediaScene as MediaSceneT, Motion} from '../types';
import {BlueprintGrid, Brackets, SourceBadge} from '../components/Brand';

const presetFraming = (m: Motion): [Framing, Framing] => {
	const k = m.strength ?? 1;
	switch (m.type) {
		case 'zoomIn':
			return [{scale: 1.02, x: 0, y: 0}, {scale: 1.02 + 0.14 * k, x: 0, y: 0}];
		case 'zoomOut':
			return [{scale: 1.02 + 0.14 * k, x: 0, y: 0}, {scale: 1.02, x: 0, y: 0}];
		case 'panLeft':
			return [{scale: 1.12 + 0.04 * k, x: 4 * k, y: 0}, {scale: 1.12 + 0.04 * k, x: -4 * k, y: 0}];
		case 'panRight':
			return [{scale: 1.12 + 0.04 * k, x: -4 * k, y: 0}, {scale: 1.12 + 0.04 * k, x: 4 * k, y: 0}];
		case 'panUp':
			return [{scale: 1.12 + 0.04 * k, x: 0, y: 3.5 * k}, {scale: 1.12 + 0.04 * k, x: 0, y: -3.5 * k}];
		case 'panDown':
			return [{scale: 1.12 + 0.04 * k, x: 0, y: -3.5 * k}, {scale: 1.12 + 0.04 * k, x: 0, y: 3.5 * k}];
		case 'custom':
			return [m.from ?? {scale: 1, x: 0, y: 0}, m.to ?? {scale: 1.1, x: 0, y: 0}];
		default:
			return [{scale: 1, x: 0, y: 0}, {scale: 1, x: 0, y: 0}];
	}
};

const lerp = (a: number, b: number, p: number) => a + (b - a) * p;

export const MediaScene: React.FC<{scene: MediaSceneT; visibleFrom: number; visibleTo: number}> = ({
	scene,
	visibleFrom,
	visibleTo,
}) => {
	const t = useTime();
	const theme = useTheme();
	const {fps} = useVideoConfig();
	const motion: Motion = scene.motion ?? {type: scene.mediaType === 'video' ? 'none' : 'zoomIn'};
	const [a, b] = presetFraming(motion);
	const p = gentle(clamp((t - visibleFrom) / Math.max(0.01, visibleTo - visibleFrom)));
	let scale = lerp(a.scale, b.scale, p);
	const x = lerp(a.x, b.x, p);
	const y = lerp(a.y, b.y, p);

	// Акцентные приближения
	let origin = motion.focus ? `${motion.focus.x * 100}% ${motion.focus.y * 100}%` : '50% 50%';
	for (const punch of scene.punches ?? []) {
		const k = smooth(clamp((t - punch.at) / (punch.duration ?? 0.6)));
		scale *= 1 + ((punch.scale ?? 1.12) - 1) * k;
		if (punch.focus && k > 0) origin = `${punch.focus.x * 100}% ${punch.focus.y * 100}%`;
	}

	const fit = scene.fit ?? 'cover';
	const mediaStyle: React.CSSProperties = {
		width: '100%',
		height: '100%',
				objectFit: fit === 'blurfill' ? 'contain' : 'cover',
		filter: theme.grade,
	};

	let media: React.ReactNode;
	if (scene.mediaType === 'video') {
		const rate = scene.videoRate ?? 1;
		const startFrames = Math.round((scene.videoStart ?? 0) * fps);
		const video = (
			<OffthreadVideo
				src={asset(scene.src)}
				trimBefore={startFrames > 0 ? startFrames : undefined}
				playbackRate={rate}
				muted={!scene.videoVolume}
				volume={scene.videoVolume ?? 0}
				style={mediaStyle}
			/>
		);
		const available = scene.srcDuration ? (scene.srcDuration - (scene.videoStart ?? 0)) / rate : Infinity;
		const needed = visibleTo - visibleFrom;
		media =
			available < needed - 0.05 ? (
				<Loop durationInFrames={Math.max(1, Math.floor(available * fps))}>{video}</Loop>
			) : (
				video
			);
	} else {
		media = <Img src={asset(scene.src)} style={mediaStyle} />;
	}

		if (fit === 'inset') {
		// низкое разрешение (архивное видео 320–640 px, схема с сайта): кадр в рамке на фоне чертежа — честно и без «мыла» на весь экран
				const ar = clamp(scene.srcAspect ?? 16 / 9, 1.0, 2.4);
		const H = 765;
		const W = Math.min(1500, H * ar);
		return (
			<AbsoluteFill style={{backgroundColor: theme.bg, overflow: 'hidden'}}>
				<BlueprintGrid opacity={0.85} />
				<AbsoluteFill style={{background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 40%, rgba(0,0,0,0.55) 100%)'}} />
				<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', paddingBottom: 60}}>
					<div style={{position: 'relative', width: `${(W / 1920) * 100}%`, aspectRatio: `${W} / ${H}`, boxShadow: '0 30px 80px rgba(0,0,0,0.6)'}}>
						<div style={{position: 'absolute', inset: 0, overflow: 'hidden', background: '#000'}}>
							<AbsoluteFill style={{transform: motion.type === 'custom' ? `translate(${x}%, ${y}%) scale(${scale})` : `scale(${1 + (scale - 1) * 0.5})`, transformOrigin: origin}}>
								{media}
							</AbsoluteFill>
						</div>
						<Brackets k={clamp((t - visibleFrom) / 0.8)} size={40} thickness={3} inset={14} />
					</div>
				</AbsoluteFill>
				<SourceBadge badge={scene.badge} start={scene.start} end={scene.end} />
			</AbsoluteFill>
		);
	}

	return (
		<AbsoluteFill style={{backgroundColor: '#000', overflow: 'hidden'}}>
			{fit === 'blurfill' && scene.mediaType === 'image' ? (
				<AbsoluteFill style={{transform: 'scale(1.15)'}}>
					<Img
						src={asset(scene.blurSrc ?? scene.src)}
						style={{
							width: '100%',
							height: '100%',
							objectFit: 'cover',
							filter: scene.blurSrc ? 'brightness(0.55)' : 'blur(40px) brightness(0.55)',
						}}
					/>
				</AbsoluteFill>
			) : null}
			<AbsoluteFill
				style={{
					transform: `translate(${x}%, ${y}%) scale(${scale})`,
					transformOrigin: origin,
					willChange: 'transform',
				}}
			>
				{media}
			</AbsoluteFill>
			{theme.vignette > 0 ? (
				<AbsoluteFill
					style={{
						background: `radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,${theme.vignette}) 100%)`,
					}}
				/>
			) : null}
			<SourceBadge badge={scene.badge} start={scene.start} end={scene.end} />
		</AbsoluteFill>
	);
};
