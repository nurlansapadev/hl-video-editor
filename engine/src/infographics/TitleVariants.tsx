import React from 'react';
import {AbsoluteFill} from 'remotion';
import {appear, clamp, easeOut, smooth, useTheme, useTime, useUnit} from '../lib';
import type {InfographicScene} from '../types';
import {BlueprintGrid, Brackets, mono, Ruler} from '../components/Brand';

/*
 * Разные заставки глав и текстовые карточки — чтобы заголовки в ролике не повторялись.
 * number   — крупный контурный номер главы + заголовок слева
 * side     — вертикальная акцентная линия, текст выезжает из-под маски
 * tracking — разреженные буквы «собираются», уголки-рамка как на чертеже
 * split    — слова поднимаются по очереди, линия расходится от центра
 * quote    — текстовая карточка: фраза рассказчика крупно, слово за словом
 */

type TitleScene = Extract<InfographicScene, {kind: 'title'}>;

const balance = {textWrap: 'balance'} as React.CSSProperties;

const Kicker: React.FC<{text?: string; k: number; align?: 'left' | 'center'}> = ({text, k, align = 'left'}) => {
	const theme = useTheme();
	const u = useUnit();
	if (!text) return null;
	return (
		<div
			style={{
				fontFamily: mono(theme),
				fontWeight: 600,
				fontSize: 28 * u,
				letterSpacing: 7 * u,
				textTransform: 'uppercase',
				color: theme.accent,
				opacity: k,
				transform: `translateY(${(1 - k) * 12 * u}px)`,
				textAlign: align,
			}}
		>
			{text}
		</div>
	);
};

/** Текст выезжает из-под невидимой маски (как в титрах документальных фильмов). */
const Rise: React.FC<{k: number; children: React.ReactNode; style?: React.CSSProperties}> = ({k, children, style}) => (
	<div style={{overflow: 'hidden', ...style}}>
		<div style={{transform: `translateY(${(1 - k) * 105}%)`}}>{children}</div>
	</div>
);

const NumberCard: React.FC<{scene: TitleScene}> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const s = scene.start;
	const {title, subtitle, kicker, number} = scene.data;
	const kn = appear(t, s + 0.1, 1.1);
	const kl = smooth(clamp((t - s - 0.35) / 0.8));
	const kt = appear(t, s + 0.5, 0.9);
	const ks = appear(t, s + 0.9, 0.8);
	const num = String(number ?? 1).padStart(2, '0');
	return (
		<AbsoluteFill style={{justifyContent: 'center', paddingLeft: 190 * u, paddingRight: 160 * u}}>
			<div style={{display: 'flex', alignItems: 'center', gap: 56 * u}}>
				<div
					style={{
						fontFamily: theme.headingFont,
						fontWeight: 800,
						fontSize: 300 * u,
						lineHeight: 1,
						color: 'transparent',
						WebkitTextStroke: `${3 * u}px ${theme.accent}`,
						opacity: 0.95 * kn,
						transform: `translateX(${(1 - kn) * -60 * u}px)`,
						letterSpacing: -6 * u,
					}}
				>
					{num}
				</div>
				<div style={{width: 3 * u, height: 260 * u * kl, background: theme.accent, opacity: 0.8}} />
				<div style={{maxWidth: 1050 * u}}>
					<Kicker text={kicker} k={kt} />
					<Rise k={kt} style={{marginTop: 14 * u}}>
						<div style={{fontFamily: theme.headingFont, fontWeight: 700, fontSize: 104 * u, lineHeight: 1.08, color: theme.text, ...balance}}>{title}</div>
					</Rise>
					<div style={{marginTop: 22 * u}}>
						<Ruler k={clamp((t - s - 0.8) / 1.0)} width={420} ticks={20} />
					</div>
					{subtitle ? (
						<div style={{fontFamily: theme.bodyFont, fontWeight: 500, fontSize: 38 * u, color: theme.muted, marginTop: 22 * u, opacity: ks, ...balance}}>
							{subtitle}
						</div>
					) : null}
				</div>
			</div>
		</AbsoluteFill>
	);
};

const SideCard: React.FC<{scene: TitleScene}> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const s = scene.start;
	const {title, subtitle, kicker} = scene.data;
	const kb = smooth(clamp((t - s - 0.05) / 0.7));
	const kk = appear(t, s + 0.3, 0.7);
	const kt = appear(t, s + 0.45, 0.9);
	const ks = appear(t, s + 0.85, 0.8);
	return (
		<AbsoluteFill style={{justifyContent: 'flex-end', padding: `0 ${160 * u}px ${230 * u}px`}}>
			<div style={{display: 'flex', alignItems: 'stretch', gap: 40 * u}}>
				<div style={{width: 10 * u, background: theme.accent, borderRadius: 5 * u, transform: `scaleY(${kb})`, transformOrigin: 'bottom'}} />
				<div style={{maxWidth: 1300 * u, padding: `${6 * u}px 0`}}>
					<Kicker text={kicker} k={kk} />
					<Rise k={kt} style={{marginTop: 12 * u}}>
						<div style={{fontFamily: theme.headingFont, fontWeight: 800, fontSize: 120 * u, lineHeight: 1.05, color: theme.text, ...balance}}>{title}</div>
					</Rise>
					<div style={{marginTop: 20 * u}}>
						<Ruler k={clamp((t - s - 0.7) / 1.0)} width={520} ticks={20} />
					</div>
					{subtitle ? (
						<div style={{fontFamily: theme.bodyFont, fontWeight: 500, fontSize: 38 * u, color: theme.muted, marginTop: 20 * u, opacity: ks, ...balance}}>
							{subtitle}
						</div>
					) : null}
				</div>
			</div>
		</AbsoluteFill>
	);
};

const TrackingCard: React.FC<{scene: TitleScene}> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const s = scene.start;
	const {title, subtitle, kicker} = scene.data;
	const k = easeOut(clamp((t - s - 0.15) / 1.6));
	const kf = appear(t, s + 0.1, 0.9);
	const ks = appear(t, s + 1.0, 0.8);
	const W = 1240 * u;
	const H = 420 * u;
	const c = 46 * u;
	const corner = (r: number) => {
		const sx = r === 0 || r === 3 ? 1 : -1;
		const sy = r < 2 ? 1 : -1;
		return (
			<div
				key={r}
				style={{
					position: 'absolute',
					[sx > 0 ? 'left' : 'right']: 0,
					[sy > 0 ? 'top' : 'bottom']: 0,
					width: c * kf,
					height: c * kf,
					borderLeft: sx > 0 ? `${3 * u}px solid ${theme.accent}` : undefined,
					borderRight: sx < 0 ? `${3 * u}px solid ${theme.accent}` : undefined,
					borderTop: sy > 0 ? `${3 * u}px solid ${theme.accent}` : undefined,
					borderBottom: sy < 0 ? `${3 * u}px solid ${theme.accent}` : undefined,
				}}
			/>
		);
	};
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
			<div style={{position: 'relative', width: W, minHeight: H, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', padding: `${40 * u}px ${70 * u}px`}}>
				{[0, 1, 2, 3].map(corner)}
				{kicker ? (
					<div style={{display: 'flex', alignItems: 'center', gap: 22 * u, opacity: kf}}>
						<div style={{width: 70 * u * kf, height: 2 * u, background: theme.accent}} />
						<Kicker text={kicker} k={kf} align="center" />
						<div style={{width: 70 * u * kf, height: 2 * u, background: theme.accent}} />
					</div>
				) : null}
				<div
					style={{
						fontFamily: theme.headingFont,
						fontWeight: 700,
						fontSize: 108 * u,
						lineHeight: 1.1,
						color: theme.text,
						textAlign: 'center',
						marginTop: 26 * u,
						opacity: k,
						transform: `scale(${1.08 - 0.08 * k})`,
						filter: `blur(${(1 - k) * 6 * u}px)`,
						...balance,
					}}
				>
					{title}
				</div>
				{subtitle ? (
					<div style={{fontFamily: theme.bodyFont, fontWeight: 500, fontSize: 36 * u, color: theme.muted, marginTop: 24 * u, opacity: ks, textAlign: 'center', ...balance}}>
						{subtitle}
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};

const SplitCard: React.FC<{scene: TitleScene}> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const s = scene.start;
	const {title, subtitle, kicker} = scene.data;
	const words = title.split(/\s+/).filter(Boolean);
	const kl = smooth(clamp((t - s - 0.1) / 0.9));
	const kk = appear(t, s + 0.2, 0.7);
	const ks = appear(t, s + 0.6 + words.length * 0.12, 0.8);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: `0 ${170 * u}px`}}>
			<Kicker text={kicker} k={kk} align="center" />
			<div style={{display: 'flex', flexWrap: 'wrap', justifyContent: 'center', columnGap: 30 * u, marginTop: 22 * u, maxWidth: 1500 * u}}>
				{words.map((w, i) => (
					<Rise key={i} k={appear(t, s + 0.3 + i * 0.12, 0.8)}>
						<span style={{fontFamily: theme.headingFont, fontWeight: 800, fontSize: 116 * u, lineHeight: 1.12, color: theme.text, textTransform: 'uppercase', letterSpacing: 2 * u}}>
							{w}
						</span>
					</Rise>
				))}
			</div>
			<div style={{width: 1100 * u * kl, height: 2 * u, background: `linear-gradient(90deg, rgba(0,0,0,0), ${theme.accent}, rgba(0,0,0,0))`, marginTop: 34 * u}} />
			{subtitle ? (
				<div style={{fontFamily: theme.bodyFont, fontWeight: 500, fontSize: 36 * u, color: theme.muted, marginTop: 26 * u, opacity: ks, textAlign: 'center', ...balance}}>
					{subtitle}
				</div>
			) : null}
		</AbsoluteFill>
	);
};

const QuoteCard: React.FC<{scene: TitleScene}> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const s = scene.start;
	const text = scene.data.subtitle || scene.data.title;
	const words = text.split(/\s+/).filter(Boolean);
	// слова проявляются примерно в темпе речи, но не дольше трети сцены
	const step = Math.min(0.28, Math.max(0.06, (scene.end - scene.start) / 3 / Math.max(1, words.length)));
	const kb = smooth(clamp((t - s) / 0.7));
	const size = text.length > 160 ? 52 : text.length > 120 ? 58 : text.length > 70 ? 66 : 78;
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: `0 ${190 * u}px`}}>
			<div style={{position: 'relative', padding: `${56 * u}px ${70 * u}px`, maxWidth: 1540 * u, background: 'rgba(8,12,15,0.35)'}}>
				<Brackets k={kb} size={44} thickness={3} />
				<div style={{display: 'flex', gap: 42 * u, alignItems: 'stretch'}}>
					<div style={{width: 6 * u, flex: `0 0 ${6 * u}px`, background: theme.accent, transform: `scaleY(${kb})`, transformOrigin: 'top'}} />
					<div style={{fontFamily: theme.headingFont, fontWeight: 600, fontSize: size * u, lineHeight: 1.28, color: theme.text, ...balance}}>
						{words.map((w, i) => {
							const k = appear(t, s + 0.35 + i * step, 0.5);
							return (
								<span key={i} style={{opacity: 0.12 + 0.88 * k, display: 'inline-block', transform: `translateY(${(1 - k) * 10 * u}px)`, marginRight: '0.28em'}}>
									{w}
								</span>
							);
						})}
					</div>
				</div>
			</div>
		</AbsoluteFill>
	);
};

export const TitleVariant: React.FC<{scene: TitleScene}> = ({scene}) => {
	switch (scene.data.variant) {
		case 'number':
			return <NumberCard scene={scene} />;
		case 'side':
			return <SideCard scene={scene} />;
		case 'tracking':
			return <TrackingCard scene={scene} />;
		case 'split':
			return <SplitCard scene={scene} />;
		case 'quote':
			return <QuoteCard scene={scene} />;
		default:
			return null;
	}
};
