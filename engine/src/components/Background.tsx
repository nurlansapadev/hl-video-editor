import React from 'react';
import {AbsoluteFill, Img, OffthreadVideo} from 'remotion';
import {asset, clamp, usePlan, useTheme, useTime, useUnit} from '../lib';
import {alpha, BlueprintGrid, Ruler} from './Brand';
import type {Background as BackgroundT} from '../types';

/** Фон для инфографики: размытая картинка проекта или фирменный тёплый фон. */
export const Background: React.FC<{bg?: BackgroundT; from: number; to: number}> = ({bg, from, to}) => {
	const theme = useTheme();
	const t = useTime();
	const u = useUnit();
	const p = clamp((t - from) / Math.max(0.01, to - from));

	if (theme.style === 'cartoon') return <PaperBackground bg={bg} t={t} p={p} />;

	if (bg?.src) {
		const blur = (bg.blur ?? 18) * u;
		const dim = bg.dim ?? 0.55;
		const style: React.CSSProperties = {
			width: '100%',
			height: '100%',
			objectFit: 'cover',
			filter: blur > 0 ? `blur(${blur}px) saturate(0.9)` : 'saturate(0.9)',
		};
		return (
			<AbsoluteFill style={{backgroundColor: theme.bg, overflow: 'hidden'}}>
				<AbsoluteFill style={{transform: `scale(${1.12 + 0.05 * p})`}}>
					{bg.mediaType === 'video' ? (
						<OffthreadVideo src={asset(bg.src)} muted style={style} />
					) : (
						<Img src={asset(bg.src)} style={style} />
					)}
				</AbsoluteFill>
				<AbsoluteFill style={{backgroundColor: `rgba(8, 12, 15, ${dim})`}} />
				<AbsoluteFill
					style={{background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 40%, rgba(0,0,0,0.55) 100%)'}}
				/>
			</AbsoluteFill>
		);
	}

	// Фирменный фон «чертёж»: графит, сетка, мягкое свечение акцентов, медленный дрейф
	const dx = Math.sin(t * 0.15) * 6;
	const dy = Math.cos(t * 0.12) * 5;
	return (
		<AbsoluteFill style={{backgroundColor: theme.bg, overflow: 'hidden'}}>
			<AbsoluteFill
				style={{
					background: `radial-gradient(circle at ${28 + dx}% ${32 + dy}%, ${alpha(theme.accent2, 0.13)}, rgba(0,0,0,0) 48%),
						radial-gradient(circle at ${74 - dx}% ${72 - dy}%, ${alpha(theme.accent, 0.08)}, rgba(0,0,0,0) 50%)`,
				}}
			/>
			<BlueprintGrid drift={p * 30 * u} />
			<AbsoluteFill
				style={{background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(0,0,0,0.55) 100%)'}}
			/>
		</AbsoluteFill>
	);
};

/** Мультяшный фон: светлая бумага с вырезанными фигурами, которые чуть покачиваются «на двойках». */
const PaperBackground: React.FC<{bg?: BackgroundT; t: number; p: number}> = ({bg, t, p}) => {
	const theme = useTheme();
	const {plan} = usePlan();
	const tq = Math.floor(t * 12) / 12;
	const shapes = [
		{x: 12, y: 18, r: 150, c: theme.accent, k: 0},
		{x: 88, y: 22, r: 110, c: theme.accent2, k: 1},
		{x: 82, y: 84, r: 170, c: theme.accent, k: 2},
		{x: 10, y: 86, r: 120, c: theme.accent2, k: 3},
		{x: 50, y: 6, r: 60, c: theme.muted, k: 4},
	];
	return (
		<AbsoluteFill style={{backgroundColor: theme.bg, overflow: 'hidden'}}>
			{bg?.src ? (
				<AbsoluteFill style={{transform: `scale(${1.08 + 0.04 * p})`, opacity: 0.35}}>
					{bg.mediaType === 'video' ? (
						<OffthreadVideo src={asset(bg.src)} muted style={{width: '100%', height: '100%', objectFit: 'cover', filter: 'blur(14px)'}} />
					) : (
						<Img src={asset(bg.src)} style={{width: '100%', height: '100%', objectFit: 'cover', filter: 'blur(14px)'}} />
					)}
				</AbsoluteFill>
			) : null}
			<svg width="100%" height="100%" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice" style={{position: 'absolute', inset: 0}}>
				{shapes.map((sh) => (
					<g key={sh.k} transform={`translate(${(sh.x / 100) * 1920} ${(sh.y / 100) * 1080}) rotate(${Math.sin(tq * 0.6 + sh.k) * 6})`}>
						<path
							d={`M ${-sh.r} 0 Q ${-sh.r} ${-sh.r} 0 ${-sh.r} Q ${sh.r * 1.1} ${-sh.r * 0.9} ${sh.r} 0 Q ${sh.r * 0.9} ${sh.r} 0 ${sh.r} Q ${-sh.r * 1.05} ${sh.r * 0.95} ${-sh.r} 0 Z`}
							fill={sh.c}
							opacity={0.22}
							stroke="#2A1E16"
							strokeOpacity={0.25}
							strokeWidth={4}
						/>
					</g>
				))}
			</svg>
			{plan.paper ? <Img src={asset(plan.paper)} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', mixBlendMode: 'multiply', opacity: 0.8}} /> : null}
		</AbsoluteFill>
	);
};

/** Заголовок инфографики с золотой чертой. */
export const InfoHeading: React.FC<{text?: string; t: number; at: number; align?: 'left' | 'center'}> = ({
	text,
	t,
	at,
	align = 'center',
}) => {
	const theme = useTheme();
	const u = useUnit();
	if (!text) return null;
	const k = clamp((t - at) / 0.7);
	const e = 1 - Math.pow(1 - k, 3);
	return (
		<div style={{textAlign: align, opacity: e, transform: `translateY(${(1 - e) * 20 * u}px)`}}>
			<div
				style={{
					fontFamily: theme.headingFont,
					fontWeight: 700,
					fontSize: 72 * u,
					lineHeight: 1.15,
					color: theme.text,
					textWrap: 'balance',
					textShadow: '0 4px 24px rgba(0,0,0,0.5)',
				}}
			>
				{text}
			</div>
			{theme.style === 'cartoon' ? (
				<div
					style={{
						height: 4 * u,
						width: 140 * u * e,
						background: theme.accent,
						borderRadius: 2 * u,
						margin: align === 'center' ? `${22 * u}px auto 0` : `${22 * u}px 0 0`,
					}}
				/>
			) : (
				<div style={{marginTop: 22 * u}}>
					<Ruler k={clamp((t - at - 0.2) / 0.9)} width={240} ticks={10} center={align === 'center'} />
				</div>
			)}
		</div>
	);
};
