/*
 * Фирменный дизайн-код «Инженерный чертёж».
 *
 * Основа: тёмный графит, сигнальный оранжевый (акцент), голубая «вода» (второй акцент), тонкие линии чертежа.
 * Узнаваемые элементы, которые повторяются во всём ролике:
 *   • уголки-рамки (как метки на чертеже) вокруг важного текста;
 *   • моноширинные подписи ЗАГЛАВНЫМИ с разрядкой — для служебной информации (глава, дата, источник);
 *   • мерная линейка с засечками — «прорисовывается» под заголовками и цифрами;
 *   • сетка чертежа на фонах инфографики;
 *   • лёгкое плёночное зерно поверх всего кадра.
 * Всё крупно и контрастно (зритель 35+), движения плавные, без мельтешения.
 */
import React from 'react';
import {AbsoluteFill} from 'remotion';
import {appear, clamp, easeOut, useTheme, useTime, useUnit} from '../lib';

export const mono = (theme: {monoFont?: string; bodyFont: string}) => theme.monoFont ?? `"IBM Plex Mono", ${theme.bodyFont}`;

/** Цвет с прозрачностью: '#F2A541' → 'rgba(242,165,65,a)'. */
export const alpha = (color: string, a: number) => {
	const m = /^#([0-9a-f]{6})$/i.exec(color.trim());
	if (!m) return color;
	const n = parseInt(m[1], 16);
	return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};

/** Уголки-рамка вокруг блока. k — прорисовка 0..1. */
export const Brackets: React.FC<{k: number; size?: number; color?: string; thickness?: number; inset?: number}> = ({k, size = 40, color, thickness = 3, inset = 0}) => {
	const theme = useTheme();
	const u = useUnit();
	const c = color ?? theme.accent;
	const decor = theme.decor ?? 'blueprint';
	if (decor === 'minimal') return null;
	if (decor === 'editorial') {
		// журнальный стиль: две тонкие линии сверху и снизу блока вместо уголков
		const wk = clamp(k);
		const line: React.CSSProperties = {position: 'absolute', left: `${50 - 50 * wk}%`, width: `${100 * wk}%`, height: Math.max(1, thickness * 0.5) * u, background: c, opacity: 0.8};
		return (
			<>
				<div style={{...line, top: -inset * u}} />
				<div style={{...line, bottom: -inset * u}} />
			</>
		);
	}
	const L = size * u * clamp(k);
	const w = thickness * u;
	const o = -inset * u;
	const base: React.CSSProperties = {position: 'absolute', width: L, height: L, opacity: clamp(k * 3)};
	return (
		<>
			<div style={{...base, left: o, top: o, borderLeft: `${w}px solid ${c}`, borderTop: `${w}px solid ${c}`}} />
			<div style={{...base, right: o, top: o, borderRight: `${w}px solid ${c}`, borderTop: `${w}px solid ${c}`}} />
			<div style={{...base, left: o, bottom: o, borderLeft: `${w}px solid ${c}`, borderBottom: `${w}px solid ${c}`}} />
			<div style={{...base, right: o, bottom: o, borderRight: `${w}px solid ${c}`, borderBottom: `${w}px solid ${c}`}} />
		</>
	);
};

/** Служебная подпись: моноширинный шрифт, заглавные, разрядка. */
export const MonoLabel: React.FC<{text?: string; k?: number; size?: number; color?: string; marker?: boolean; style?: React.CSSProperties}> = ({
	text,
	k = 1,
	size = 26,
	color,
	marker = false,
	style,
}) => {
	const theme = useTheme();
	const u = useUnit();
	if (!text) return null;
	return (
		<div
			style={{
				fontFamily: mono(theme),
				fontWeight: 600,
				fontSize: size * u,
				letterSpacing: size * 0.22 * u,
				textTransform: 'uppercase',
				color: color ?? theme.accent,
				opacity: k,
				display: 'flex',
				alignItems: 'center',
				gap: size * 0.5 * u,
				...style,
			}}
		>
			{marker ? <span style={{width: size * 0.42 * u, height: size * 0.42 * u, background: color ?? theme.accent, display: 'inline-block'}} /> : null}
			<span>{text}</span>
		</div>
	);
};

/** Мерная линейка с засечками — прорисовывается слева направо. */
export const Ruler: React.FC<{k: number; width: number; ticks?: number; color?: string; center?: boolean}> = ({k, width, ticks = 10, color, center}) => {
	const theme = useTheme();
	const u = useUnit();
	const c = color ?? theme.accent;
	const W = width * u;
	const shown = W * clamp(k);
	const decor = theme.decor ?? 'blueprint';
	if (decor === 'minimal') {  // короткая толстая черта
		const bw = W * 0.28 * clamp(k);
		return <div style={{width: W * 0.28, height: 8 * u, margin: center ? '0 auto' : undefined, position: 'relative'}}>
			<div style={{position: 'absolute', left: center ? (W * 0.28 - bw) / 2 : 0, width: bw, height: 8 * u, borderRadius: 4 * u, background: c}} />
		</div>;
	}
	if (decor === 'editorial') {  // тонкая линия без засечек
		return <div style={{position: 'relative', width: W, height: 6 * u, margin: center ? '0 auto' : undefined}}>
			<div style={{position: 'absolute', left: center ? (W - shown) / 2 : 0, top: 2 * u, width: shown, height: 1.5 * u, background: c, opacity: 0.85}} />
		</div>;
	}
	return (
		<div style={{position: 'relative', width: W, height: 16 * u, margin: center ? '0 auto' : undefined}}>
			<div style={{position: 'absolute', left: center ? (W - shown) / 2 : 0, top: 0, width: shown, height: 2 * u, background: c}} />
			{Array.from({length: ticks + 1}, (_, i) => {
				const x = (W * i) / ticks;
				const vis = center ? Math.abs(x - W / 2) <= shown / 2 : x <= shown;
				return vis ? (
					<div key={i} style={{position: 'absolute', left: x - u, top: 0, width: 2 * u, height: (i % 5 === 0 ? 14 : 8) * u, background: c, opacity: i % 5 === 0 ? 1 : 0.6}} />
				) : null;
			})}
		</div>
	);
};

/** Сетка чертежа (для фонов инфографики и карточек). */
export const BlueprintGrid: React.FC<{opacity?: number; drift?: number}> = ({opacity = 1, drift = 0}) => {
	const u = useUnit();
	const theme = useTheme();
	const decor = theme.decor ?? 'blueprint';
	if (decor === 'editorial') {  // вместо сетки — мягкий свет из угла
		return <AbsoluteFill style={{opacity, background: `radial-gradient(ellipse at 20% 15%, ${alpha(theme.accent, 0.08)} 0%, rgba(0,0,0,0) 55%)`}} />;
	}
	if (decor === 'minimal') {  // едва заметная точечная сетка
		return <AbsoluteFill style={{opacity: opacity * 0.6, backgroundImage: `radial-gradient(${alpha(theme.text, 0.09)} ${1.2 * u}px, transparent ${1.4 * u}px)`,
			backgroundSize: `${44 * u}px ${44 * u}px`, backgroundPosition: `${drift}px ${drift * 0.6}px`}} />;
	}
	const minor = 40 * u;
	const major = 200 * u;
	return (
		<AbsoluteFill
			style={{
				opacity,
				backgroundImage: `linear-gradient(rgba(141,182,206,0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(141,182,206,0.07) 1px, transparent 1px),
					linear-gradient(rgba(141,182,206,0.11) 1px, transparent 1px), linear-gradient(90deg, rgba(141,182,206,0.11) 1px, transparent 1px)`,
				backgroundSize: `${minor}px ${minor}px, ${minor}px ${minor}px, ${major}px ${major}px, ${major}px ${major}px`,
				backgroundPosition: `${drift}px ${drift * 0.6}px`,
			}}
		/>
	);
};

// плёночное зерно: маленькая плитка шума, которая каждый кадр сдвигается (дёшево для рендера)
const NOISE =
	'data:image/svg+xml;utf8,' +
	encodeURIComponent(
		`<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 1.4 -0.2"/></filter><rect width="256" height="256" filter="url(#n)"/></svg>`,
	);

export const Grain: React.FC<{amount: number}> = ({amount}) => {
	const t = useTime();
	const u = useUnit();
	if (amount <= 0) return null;
	const f = Math.floor(t * 12); // зерно «живёт» 12 раз в секунду, как у плёнки
	const x = ((f * 97) % 256) * u;
	const y = ((f * 57) % 256) * u;
	return (
		<AbsoluteFill
			style={{
				pointerEvents: 'none',
				opacity: amount,
				mixBlendMode: 'overlay',
				backgroundImage: `url("${NOISE}")`,
				backgroundSize: `${256 * u}px ${256 * u}px`,
				backgroundPosition: `${x}px ${y}px`,
			}}
		/>
	);
};

/** Плашка на найденном кадре: «■ АРХИВНЫЕ КАДРЫ / NASA» слева вверху или «Фото: автор» справа вверху. */
export const SourceBadge: React.FC<{badge?: {label?: string; source?: string}; start: number; end: number}> = ({badge, start, end}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	if (!badge || (!badge.label && !badge.source)) return null;
	const k = Math.min(appear(t, start + 0.4, 0.6), clamp((end - t) / 0.4));
	if (k <= 0) return null;
	if (badge.label) {
		return (
			<AbsoluteFill style={{padding: `${56 * u}px ${70 * u}px`, alignItems: 'flex-end'}}>
				<div style={{position: 'relative', padding: `${16 * u}px ${24 * u}px`, background: 'rgba(8,12,15,0.62)', opacity: k}}>
					<Brackets k={k} size={18} thickness={2} />
					<MonoLabel text={badge.label} size={24} marker />
					{badge.source ? <MonoLabel text={badge.source} size={18} color={theme.muted} style={{marginTop: 6 * u, letterSpacing: 2 * u}} /> : null}
				</div>
			</AbsoluteFill>
		);
	}
	return (
		<AbsoluteFill style={{padding: `${44 * u}px ${56 * u}px`, alignItems: 'flex-end'}}>
			<div
				style={{
					fontFamily: mono(theme),
					fontSize: 17 * u,
					letterSpacing: 1.5 * u,
					color: 'rgba(242,245,247,0.78)',
					background: 'rgba(8,12,15,0.45)',
					padding: `${6 * u}px ${12 * u}px`,
					opacity: k * 0.9,
					maxWidth: 900 * u,
					textAlign: 'right',
				}}
			>
				{badge.source}
			</div>
		</AbsoluteFill>
	);
};

export const useReveal = (at: number, dur = 0.8) => {
	const t = useTime();
	return easeOut(clamp((t - at) / dur));
};
