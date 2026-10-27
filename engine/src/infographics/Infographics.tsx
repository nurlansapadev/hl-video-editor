import React from 'react';
import {AbsoluteFill} from 'remotion';
import {InfoHeading} from '../components/Background';
import {appear, clamp, easeOut, formatNumber, smooth, useTheme, useTime, useUnit} from '../lib';
import type {BarItem, InfographicScene, ListItem, TimelineItem} from '../types';
import {TitleVariant} from './TitleVariants';
import {alpha, Brackets, mono, Ruler} from '../components/Brand';

type Props<K extends InfographicScene['kind']> = {scene: Extract<InfographicScene, {kind: K}>};

/** Время появления элементов: из плана, иначе равномерно по сцене. */
export const resolveTimes = <T extends {at?: number}>(items: T[], start: number, end: number, lead = 0.9) => {
	const span = Math.max(0.5, end - start - lead - 1.2);
	return items.map((it, i) => it.at ?? start + lead + (span * i) / Math.max(1, items.length));
};

/** Две ровные строки вместо «висячего» слова: «Собор под / футбольным полем». */
export const balanceLines = (text: string, maxOneLine = 20): string[] => {
	if (text.length <= maxOneLine) return [text];
	const words = text.split(' ');
	if (words.length < 2) return [text];
	let best = 1;
	let bestDiff = Infinity;
	for (let i = 1; i < words.length; i++) {
		const a = words.slice(0, i).join(' ').length;
		const b = words.slice(i).join(' ').length;
		const diff = Math.abs(a - b);
		if (diff < bestDiff) {
			bestDiff = diff;
			best = i;
		}
	}
	return [words.slice(0, best).join(' '), words.slice(best).join(' ')];
};

// ───────────────────────── Заголовок / глава ─────────────────────────
export const TitleCard: React.FC<Props<'title'>> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const {title, subtitle, kicker} = scene.data;
	const s = scene.start;
	if (scene.data.variant && scene.data.variant !== 'hero') return <TitleVariant scene={scene} />;
	const k1 = appear(t, s + 0.2, 0.8);
	const k2 = appear(t, s + 0.5, 1.0);
	const k3 = appear(t, s + 0.9, 0.8);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: `0 ${160 * u}px`}}>
			<div style={{textAlign: 'center', maxWidth: 1500 * u, position: 'relative', padding: theme.style === 'cartoon' ? 0 : `${60 * u}px ${90 * u}px`}}>
				{theme.style !== 'cartoon' ? <Brackets k={appear(t, s + 0.3, 1.0)} size={56} thickness={3} /> : null}
				{kicker ? (
					<div
						style={{
							fontFamily: theme.style === 'cartoon' ? theme.bodyFont : mono(theme),
							fontWeight: 600,
							fontSize: 30 * u,
							letterSpacing: 8 * u,
							textTransform: 'uppercase',
							color: theme.accent,
							opacity: k1,
							transform: `translateY(${(1 - k1) * 14 * u}px)`,
							marginBottom: 28 * u,
						}}
					>
						{kicker}
					</div>
				) : null}
				<div
					style={{
						fontFamily: theme.headingFont,
						fontWeight: 700,
						fontSize: 104 * u,
						lineHeight: 1.1,
						color: theme.text,
						opacity: k2,
						transform: `scale(${0.96 + 0.04 * k2})`,
						textShadow: '0 6px 30px rgba(0,0,0,0.55)',
					}}
				>
					{balanceLines(title).map((ln, i) => (
						<div key={i}>{ln}</div>
					))}
				</div>
				{theme.style === 'cartoon' ? (
					<div
						style={{
							height: 4 * u,
							width: 200 * u * k3,
							background: theme.accent,
							margin: `${36 * u}px auto ${30 * u}px`,
							borderRadius: 2 * u,
						}}
					/>
				) : (
					<div style={{margin: `${36 * u}px auto ${30 * u}px`}}>
						<Ruler k={k3} width={360} ticks={20} center />
					</div>
				)}
				{subtitle ? (
					<div
						style={{
							fontFamily: theme.bodyFont,
							fontWeight: 500,
							fontSize: 40 * u,
							color: theme.muted,
							opacity: k3,
							lineHeight: 1.4,
						}}
					>
						{subtitle}
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};

// ───────────────────────── Таймлайн ─────────────────────────
export const Timeline: React.FC<Props<'timeline'>> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const items: TimelineItem[] = scene.data.items;
	const times = resolveTimes(items, scene.start, scene.end, 1.0);
	const n = items.length;
	const left = 300 * u;
	const right = 1620 * u;
	const lineY = 600 * u;
	const xs = items.map((_, i) => (n === 1 ? (left + right) / 2 : left + ((right - left) * i) / (n - 1)));

	// Линия «дорисовывается» к последней открытой точке
	let reach = left - 60 * u;
	items.forEach((_, i) => {
		const k = smooth(clamp((t - (times[i] - 0.5)) / 0.6));
		const prev = i === 0 ? left - 60 * u : xs[i - 1];
		if (k > 0) reach = prev + (xs[i] - prev) * k;
	});
	const lastReveal = times[n - 1];
	if (t > lastReveal + 0.2) reach += (right + 60 * u - xs[n - 1]) * smooth(clamp((t - lastReveal - 0.2) / 0.6));

	const colW = Math.min(380 * u, ((right - left) / Math.max(1, n - 1)) * 0.95);
	return (
		<AbsoluteFill>
			<div style={{position: 'absolute', top: 150 * u, width: '100%'}}>
				<InfoHeading text={scene.data.title} t={t} at={scene.start + 0.2} />
			</div>
			<div
				style={{
					position: 'absolute',
					left: left - 60 * u,
					top: lineY - 3 * u,
					width: right - left + 120 * u,
					height: 6 * u,
					background: 'rgba(255,255,255,0.12)',
					borderRadius: 3 * u,
				}}
			/>
			<div
				style={{
					position: 'absolute',
					left: left - 60 * u,
					top: lineY - 3 * u,
					width: Math.max(0, reach - (left - 60 * u)),
					height: 6 * u,
					background: theme.accent,
					borderRadius: 3 * u,
					boxShadow: `0 0 ${18 * u}px ${alpha(theme.accent, 0.5)}`,
				}}
			/>
			{items.map((it, i) => {
				const k = appear(t, times[i], 0.7);
				const pop = easeOut(clamp((t - times[i]) / 0.45));
				const active = i === n - 1 ? t >= times[i] : t >= times[i] && t < times[i + 1];
				const dim = active || t < times[i] ? 1 : 0.7;
				return (
					<div key={i} style={{opacity: k * dim}}>
						<div
							style={{
								position: 'absolute',
								left: xs[i] - 18 * u,
								top: lineY - 18 * u,
								width: 36 * u,
								height: 36 * u,
								borderRadius: '50%',
								background: theme.bg,
								border: `${6 * u}px solid ${theme.accent}`,
								transform: `scale(${pop})`,
								boxSizing: 'border-box',
							}}
						/>
						<div
							style={{
								position: 'absolute',
								left: xs[i] - colW / 2,
								width: colW,
								top: lineY - 150 * u,
								textAlign: 'center',
								fontFamily: theme.bodyFont,
								fontWeight: 800,
								fontSize: 68 * u,
								color: theme.accent,
								transform: `translateY(${(1 - k) * 24 * u}px)`,
							}}
						>
							{it.label}
						</div>
						{it.title ? (
							<div
								style={{
									position: 'absolute',
									left: xs[i] - colW / 2,
									width: colW,
									top: lineY + 46 * u,
									textAlign: 'center',
									fontFamily: theme.bodyFont,
									fontWeight: 600,
									fontSize: 38 * u,
									lineHeight: 1.3,
									color: theme.text,
									transform: `translateY(${(1 - k) * -18 * u}px)`,
								}}
							>
								{it.title}
							</div>
						) : null}
					</div>
				);
			})}
		</AbsoluteFill>
	);
};

// ───────────────────────── Список ─────────────────────────
export const List: React.FC<Props<'list'>> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const items: ListItem[] = scene.data.items;
	const times = resolveTimes(items, scene.start, scene.end, 1.2);
	const numbered = scene.data.numbered ?? true;
	const rowH = Math.min(190 * u, (620 * u) / Math.max(1, items.length));
	return (
		<AbsoluteFill style={{padding: `${130 * u}px ${220 * u}px`}}>
			<InfoHeading text={scene.data.title} t={t} at={scene.start + 0.2} align="left" />
			<div style={{marginTop: 70 * u}}>
				{items.map((it, i) => {
					const k = appear(t, times[i], 0.7);
					const current = t >= times[i] && (i === items.length - 1 || t < times[i + 1]);
					const dim = current ? 1 : 0.55;
					return (
						<div
							key={i}
							style={{
								display: 'flex',
								alignItems: 'center',
								height: rowH,
								opacity: k * (t >= times[i] ? dim : 1),
								transform: `translateX(${(1 - k) * -60 * u}px)`,
							}}
						>
							<div
								style={{
									flex: `0 0 ${96 * u}px`,
									height: 96 * u,
									borderRadius: '50%',
									background: current ? theme.accent : alpha(theme.accent, 0.18),
									border: `${3 * u}px solid ${theme.accent}`,
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'center',
									fontFamily: theme.bodyFont,
									fontWeight: 800,
									fontSize: 46 * u,
									color: current ? theme.bg : theme.accent,
									marginRight: 44 * u,
								}}
							>
								{numbered ? i + 1 : '✓'}
							</div>
							<div>
								<div
									style={{
										fontFamily: theme.bodyFont,
										fontWeight: 700,
										fontSize: 58 * u,
										color: theme.text,
										lineHeight: 1.2,
									}}
								>
									{it.text}
								</div>
								{it.detail ? (
									<div
										style={{
											fontFamily: theme.bodyFont,
											fontWeight: 500,
											fontSize: 36 * u,
											color: theme.muted,
											marginTop: 8 * u,
										}}
									>
										{it.detail}
									</div>
								) : null}
							</div>
						</div>
					);
				})}
			</div>
		</AbsoluteFill>
	);
};

// ───────────────────────── Счётчик ─────────────────────────
export const Counter: React.FC<Props<'counter'>> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const d = scene.data;
	const at = d.at ?? scene.start + 0.5;
	// ровный счёт до нужного числа за 1,6 с: без замедления в конце, последняя цифра не «догоняет»
	const k = clamp((t - at) / 1.6);
	const dec = d.decimals ?? 0;
	const shown = formatNumber(k >= 1 ? d.value : Math.round(d.value * k * 10 ** dec) / 10 ** dec, dec);
	const glow = appear(t, at + 1.6, 0.5);
	const labelK = appear(t, at + 0.6, 0.8);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
			<div style={{textAlign: 'center', opacity: appear(t, scene.start + 0.1, 0.5), position: 'relative',
				padding: theme.style === 'cartoon' ? 0 : `${50 * u}px ${110 * u}px`}}>
				{theme.style !== 'cartoon' ? <Brackets k={appear(t, scene.start + 0.2, 0.9)} size={50} thickness={3} /> : null}
				<div
					style={{
						fontFamily: theme.bodyFont,
						fontWeight: 800,
						fontSize: 200 * u,
						lineHeight: 1,
						color: theme.accent,
						fontVariantNumeric: 'tabular-nums',
						textShadow: `0 0 ${50 * u * glow}px ${alpha(theme.accent, 0.45 * glow)}, 0 8px 30px rgba(0,0,0,0.5)`,
						transform: `scale(${1 + 0.03 * glow})`,
					}}
				>
					{d.prefix ?? ''}
					{shown}
				</div>
				{theme.style !== 'cartoon' ? (
					<div style={{marginTop: 18 * u}}>
						<Ruler k={k} width={520} ticks={20} center />
					</div>
				) : null}
				{d.suffix ? (
					<div
						style={{
							fontFamily: theme.bodyFont,
							fontWeight: 700,
							fontSize: 72 * u,
							color: theme.text,
							marginTop: 20 * u,
							opacity: labelK,
						}}
					>
						{d.suffix}
					</div>
				) : null}
				{d.label ? (
					<div
						style={{
							fontFamily: theme.bodyFont,
							fontWeight: 500,
							fontSize: 42 * u,
							color: theme.muted,
							marginTop: 26 * u,
							opacity: labelK,
							transform: `translateY(${(1 - labelK) * 16 * u}px)`,
						}}
					>
						{d.label}
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};

// ───────────────────────── Цитата ─────────────────────────
export const Quote: React.FC<Props<'quote'>> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const words = scene.data.text.split(/\s+/);
	const revealStart = scene.start + 0.5;
	const revealDur = Math.min(2.5, (scene.end - scene.start) * 0.45);
	const markK = appear(t, scene.start + 0.1, 0.8);
	const authorK = appear(t, revealStart + revealDur + 0.2, 0.8);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: `0 ${220 * u}px`}}>
			<div style={{textAlign: 'center', maxWidth: 1400 * u}}>
				<div
					style={{
						fontFamily: theme.headingFont,
						fontSize: 200 * u,
						lineHeight: 1,
						height: 150 * u,
						marginBottom: 10 * u,
						overflow: 'hidden',
						color: theme.accent,
						opacity: markK,
						transform: `translateY(${(1 - markK) * 20 * u}px)`,
					}}
				>
					«
				</div>
				<div
					style={{
						fontFamily: theme.headingFont,
						fontStyle: 'italic',
						fontWeight: 600,
						fontSize: 78 * u,
						lineHeight: 1.3,
						color: theme.text,
						textShadow: '0 4px 24px rgba(0,0,0,0.5)',
					}}
				>
					{words.map((w, i) => {
						const k = appear(t, revealStart + (revealDur * i) / words.length, 0.5);
						return (
							<span key={i} style={{opacity: k, display: 'inline-block', transform: `translateY(${(1 - k) * 12 * u}px)`}}>
								{w}
								{i < words.length - 1 ? ' ' : ''}
							</span>
						);
					})}
				</div>
				{scene.data.author ? (
					<div
						style={{
							fontFamily: theme.bodyFont,
							fontWeight: 600,
							fontSize: 38 * u,
							color: theme.accent,
							marginTop: 48 * u,
							letterSpacing: 2 * u,
							opacity: authorK,
						}}
					>
						— {scene.data.author}
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};

// ───────────────────────── Столбики ─────────────────────────
export const Bars: React.FC<Props<'bars'>> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const items: BarItem[] = scene.data.items;
	const times = resolveTimes(items, scene.start, scene.end, 1.0);
	const paired = items.some((i) => i.from !== undefined);
	const max = Math.max(...items.map((i) => Math.max(i.value, i.from ?? 0)), 1);
	const barMax = (paired ? 940 : 1000) * u;
	const rowH = Math.min(150 * u, ((paired ? 500 : 640) * u) / Math.max(1, items.length));
	const legend = scene.data.legend ?? [];
	const planC = theme.accent2 ?? '#3FA7D6';
	const labelCol = (it: BarItem, i: number) => (
		<div
			style={{
				flex: `0 0 ${360 * u}px`,
				fontFamily: theme.bodyFont,
				fontWeight: paired && i === items.length - 1 ? 800 : 600,
				fontSize: (it.label.length > 22 ? 32 : it.label.length > 14 ? 36 : 42) * u,
				lineHeight: 1.12,
				color: theme.text,
				textAlign: 'right',
				paddingRight: 36 * u,
			}}
		>
			{it.label}
		</div>
	);
	return (
		<AbsoluteFill style={{padding: `${(paired ? 90 : 130) * u}px ${200 * u}px`}}>
			<InfoHeading text={scene.data.title} t={t} at={scene.start + 0.2} align="left" />
			{paired && legend.length === 2 ? (
				<div style={{display: 'flex', gap: 40 * u, marginTop: 34 * u, marginLeft: 360 * u, opacity: appear(t, scene.start + 0.5, 0.6)}}>
					{legend.map((l, j) => (
						<div key={j} style={{display: 'flex', alignItems: 'center', gap: 14 * u, fontFamily: mono(theme), fontSize: 24 * u, letterSpacing: 2 * u, color: theme.muted, textTransform: 'uppercase'}}>
							<div style={{width: 46 * u, height: (j ? 22 : 14) * u, borderRadius: 4 * u, background: j ? theme.accent : alpha(planC, 0.35), border: j ? 'none' : `${2 * u}px solid ${planC}`}} />
							{l}
						</div>
					))}
				</div>
			) : null}
			{scene.data.source ? (
				<div style={{marginTop: 18 * u, marginLeft: 360 * u, fontFamily: mono(theme), fontSize: 22 * u, letterSpacing: 1 * u, color: theme.muted, opacity: 0.85 * appear(t, scene.start + 1, 0.8)}}>
					{scene.data.source}
				</div>
			) : null}
			<div style={{marginTop: (paired ? 36 : 70) * u}}>
				{items.map((it, i) => {
					const k = easeOut(clamp((t - times[i]) / 1.2));
					const fadeK = appear(t, times[i], 0.5);
					const label = it.display ?? `${formatNumber(it.value * k)}${scene.data.unit ? ' ' + scene.data.unit : ''}`;
					if (paired) {
						// было (план) — тонкий контурный столбик сверху; стало (итог) — яркий под ним, растёт чуть позже
						const k0 = easeOut(clamp((t - times[i]) / 0.9));
						const k1 = easeOut(clamp((t - times[i] - 0.45) / 1.3));
						const total = i === items.length - 1;
						return (
							<div key={i} style={{display: 'flex', alignItems: 'center', height: rowH, opacity: fadeK, borderTop: total ? `${2 * u}px solid ${alpha(theme.accent, 0.35)}` : 'none'}}>
								{labelCol(it, i)}
								<div style={{display: 'flex', flexDirection: 'column', gap: 8 * u}}>
									<div style={{display: 'flex', alignItems: 'center', height: rowH * 0.22}}>
										{it.from !== undefined ? (
											<>
												<div style={{height: '100%', width: Math.max(6 * u, (barMax * it.from * k0) / max), background: alpha(planC, 0.3), border: `${2 * u}px solid ${planC}`, borderRadius: 6 * u, boxSizing: 'border-box'}} />
												<div style={{fontFamily: mono(theme), fontSize: 26 * u, color: planC, paddingLeft: 18 * u, opacity: clamp(k0 * 1.5)}}>{it.fromDisplay ?? formatNumber(it.from)}</div>
											</>
										) : (
											<div style={{fontFamily: mono(theme), fontSize: 24 * u, color: theme.muted, opacity: clamp(k0 * 1.5)}}>—</div>
										)}
									</div>
									<div style={{display: 'flex', alignItems: 'center', height: rowH * 0.34}}>
										<div style={{height: '100%', width: Math.max(6 * u, (barMax * it.value * k1) / max), background: total ? theme.accent : alpha(theme.accent, 0.75), borderRadius: 8 * u}} />
										<div style={{fontFamily: theme.bodyFont, fontWeight: 800, fontSize: (total ? 44 : 36) * u, color: theme.accent, paddingLeft: 22 * u, opacity: clamp(k1 * 1.5)}}>{label}</div>
									</div>
								</div>
							</div>
						);
					}
					return (
						<div key={i} style={{display: 'flex', alignItems: 'center', height: rowH, opacity: fadeK}}>
							{labelCol(it, i)}
							<div
								style={{
									height: rowH * 0.5,
									width: Math.max(8 * u, (barMax * it.value * k) / max),
									background: i === items.length - 1 ? theme.accent : alpha(theme.accent, 0.55),
									borderRadius: 10 * u,
								}}
							/>
							<div
								style={{
									fontFamily: theme.bodyFont,
									fontWeight: 800,
									fontSize: 44 * u,
									color: theme.accent,
									paddingLeft: 26 * u,
									whiteSpace: 'nowrap',
									opacity: clamp(k * 1.5),
								}}
							>
								{label}
							</div>
						</div>
					);
				})}
			</div>
		</AbsoluteFill>
	);
};

// ───────────────────────── Концовка ─────────────────────────
export const Outro: React.FC<Props<'outro'>> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const d = scene.data;
	const s = scene.start;
	const k1 = appear(t, s + 0.2, 0.8);
	const k2 = appear(t, s + 0.8, 0.8);
	const k3 = appear(t, s + 1.4, 0.8);
	const pulse = 1 + 0.03 * Math.sin(Math.max(0, t - s - 2) * 3) * clamp(t - s - 2);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: `0 ${200 * u}px`}}>
			<div style={{textAlign: 'center'}}>
				<div
					style={{
						fontFamily: theme.headingFont,
						fontWeight: 700,
						fontSize: 92 * u,
						color: theme.text,
						opacity: k1,
						transform: `translateY(${(1 - k1) * 20 * u}px)`,
					}}
				>
					{d.title ?? 'Спасибо, что смотрите!'}
				</div>
				{d.question ? (
					<div
						style={{
							margin: `${50 * u}px auto 0`,
							maxWidth: 1300 * u,
							padding: `${34 * u}px ${50 * u}px`,
							borderRadius: theme.style === 'cartoon' ? 24 * u : 0,
							position: 'relative',
							background: theme.panel,
							border: `${2 * u}px solid ${alpha(theme.accent, 0.45)}`,
							fontFamily: theme.bodyFont,
							fontWeight: 600,
							fontSize: 50 * u,
							lineHeight: 1.35,
							color: theme.text,
							opacity: k2,
							transform: `translateY(${(1 - k2) * 20 * u}px)`,
						}}
					>
												{theme.style !== 'cartoon' ? <Brackets k={k2} size={30} thickness={3} /> : null}
						{d.question}
					</div>
				) : null}
				<div
					style={{
						display: 'inline-block',
						marginTop: 60 * u,
						padding: `${24 * u}px ${64 * u}px`,
						borderRadius: theme.style === 'cartoon' ? 60 * u : 6 * u,
						background: theme.style === 'cartoon' ? theme.accent2 : theme.accent,
						fontFamily: theme.bodyFont,
						fontWeight: 800,
						fontSize: 46 * u,
						color: theme.style === 'cartoon' ? '#fff' : theme.bg,
						letterSpacing: 1 * u,
						opacity: k3,
						transform: `scale(${(0.9 + 0.1 * k3) * pulse})`,
						boxShadow: '0 10px 40px rgba(0,0,0,0.4)',
					}}
				>
					{d.cta ?? 'Подпишитесь на канал'}
				</div>
			</div>
		</AbsoluteFill>
	);
};
