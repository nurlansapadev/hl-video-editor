import {geoMercator, geoPath} from 'd3-geo';
import React, {useMemo} from 'react';
import {AbsoluteFill, useVideoConfig} from 'remotion';
import {feature} from 'topojson-client';
import world from 'world-atlas/countries-50m.json';
import {InfoHeading} from '../components/Background';
import {appear, clamp, easeOut, smooth, useTheme, useTime, useUnit} from '../lib';
import type {InfographicScene, MapPoint} from '../types';
import {resolveTimes} from './Infographics';
import {alpha} from '../components/Brand';

type MapScene = Extract<InfographicScene, {kind: 'map'}>;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const countries = feature(world as any, (world as any).objects.countries) as unknown as {
	features: {properties: {name: string}; geometry: unknown}[];
};

const bezier = (a: number[], c: number[], b: number[], k: number) => [
	(1 - k) * (1 - k) * a[0] + 2 * (1 - k) * k * c[0] + k * k * b[0],
	(1 - k) * (1 - k) * a[1] + 2 * (1 - k) * k * c[1] + k * k * b[1],
];

export const MapRoute: React.FC<{scene: MapScene}> = ({scene}) => {
	const t = useTime();
	const u = useUnit();
	const theme = useTheme();
	const {width, height} = useVideoConfig();
	const points: MapPoint[] = scene.data.points;
	const times = resolveTimes(points, scene.start, scene.end, 1.0);
	const highlight = new Set(scene.data.highlight ?? []);

	const {paths, proj} = useMemo(() => {
		let region = scene.data.region;
		if (!region) {
			const lons = points.map((p) => p.lon);
			const lats = points.map((p) => p.lat);
			const [x0, x1, y0, y1] = [Math.min(...lons), Math.max(...lons), Math.min(...lats), Math.max(...lats)];
			// поля вокруг точек: для близких мест (город и пригород) — крупный план, для далёких — вся страна/континент
			const px = Math.max(1.6, (x1 - x0) * 0.35);
			const py = Math.max(1.0, (y1 - y0) * 0.45);
			region = [x0 - px, Math.max(-75, y0 - py), x1 + px, Math.min(80, y1 + py)];
		}
		const [w, s, e, n] = region;
		const projection = geoMercator().fitExtent(
			[
				[120 * u, 230 * u],
				[width - 120 * u, height - 90 * u],
			],
			{
				type: 'Feature',
				properties: {},
				geometry: {type: 'MultiPoint', coordinates: [[w, s], [e, n], [w, n], [e, s]]},
			},
		);
		const gen = geoPath(projection);
		return {
			proj: projection,
			paths: countries.features.map((f) => ({
				d: gen(f as never) ?? '',
				name: f.properties.name,
			})),
		};
	}, [scene.data.region, points, width, height, u]);

	const xy = points.map((p) => proj([p.lon, p.lat]) ?? [0, 0]);
	const land = useMemo(
		() => (
			<svg width={width} height={height}>
				{paths.map((p, i) => (
					<path
						key={i}
						d={p.d}
						fill={highlight.has(p.name) ? alpha(theme.accent, 0.32) : 'rgba(220,235,245,0.10)'}
						stroke="rgba(190,215,230,0.30)"
						strokeWidth={1.1 * u}
					/>
				))}
			</svg>
		),
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[paths, width, height, u, (scene.data.highlight ?? []).join('|')],
	);

	// Подписи городов не налезают друг на друга: пробуем сверху, снизу, справа, слева
	const labelPos: {x: number; y: number}[] = [];
	const boxes: [number, number, number, number][] = [];
	const lh = 62 * u;
	points.forEach((pt, i) => {
		const w = pt.name.length * 23 * u + 52 * u;
		const [px, py] = xy[i];
		const options = [
			{x: px, y: py - 42 * u - lh / 2},
			{x: px, y: py + 42 * u + lh / 2},
			{x: px + 30 * u + w / 2, y: py},
			{x: px - 30 * u - w / 2, y: py},
			{x: px, y: py - 42 * u - lh * 1.6},
		];
		const hit = (o: {x: number; y: number}) =>
			boxes.some(([x0, y0, x1, y1]) => o.x - w / 2 < x1 && o.x + w / 2 > x0 && o.y - lh / 2 < y1 && o.y + lh / 2 > y0) ||
			xy.some(([qx, qy], j) => j !== i && Math.abs(qx - o.x) < w / 2 && Math.abs(qy - o.y) < lh / 2 + 10 * u);
		const pos = options.find((o) => !hit(o)) ?? options[0];
		labelPos.push(pos);
		boxes.push([pos.x - w / 2, pos.y - lh / 2, pos.x + w / 2, pos.y + lh / 2]);
	});
	const mapK = appear(t, scene.start, 0.9);
	const zoom = 1 + 0.05 * smooth(clamp((t - scene.start) / Math.max(1, scene.end - scene.start)));

	return (
		<AbsoluteFill>
			{/* Статичный слой суши: рисуется один раз, дальше только масштабируется */}
			<AbsoluteFill style={{opacity: mapK, transform: `scale(${zoom})`, willChange: 'transform'}}>
				{land}
			</AbsoluteFill>
			<AbsoluteFill style={{opacity: mapK, transform: `scale(${zoom})`}}>
				<svg width={width} height={height}>
					{scene.data.route !== false
						? xy.slice(1).map((b, i) => {
								const a = xy[i];
								const dx = b[0] - a[0];
								const dy = b[1] - a[1];
								const c = [(a[0] + b[0]) / 2 + dy * 0.22, (a[1] + b[1]) / 2 - Math.abs(dx) * 0.22];
								const k = smooth(clamp((t - times[i] - 0.3) / Math.max(0.6, times[i + 1] - times[i] - 0.4)));
								if (k <= 0) return null;
								const head = bezier(a, c, b, k);
								const d = `M${a[0]},${a[1]} Q${c[0]},${c[1]} ${b[0]},${b[1]}`;
								return (
									<g key={i}>
										<path d={d} fill="none" stroke={theme.accent} strokeOpacity={0.28} strokeWidth={16 * u} strokeLinecap="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - k} />
										<path d={d} fill="none" stroke={theme.accent} strokeWidth={5 * u} strokeLinecap="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - k} />
										{k < 1 ? (
											<>
												<circle cx={head[0]} cy={head[1]} r={18 * u} fill="#fff" opacity={0.25} />
												<circle cx={head[0]} cy={head[1]} r={9 * u} fill="#fff" />
											</>
										) : null}
									</g>
								);
							})
						: null}
					{xy.map((p, i) => {
						const k = easeOut(clamp((t - times[i]) / 0.5));
						const ring = clamp((t - times[i]) / 1.4);
						return (
							<g key={i} opacity={k > 0 ? 1 : 0}>
								<circle cx={p[0]} cy={p[1]} r={(14 + 40 * ring) * u} fill="none" stroke={theme.accent} strokeWidth={3 * u} opacity={1 - ring} />
								<circle cx={p[0]} cy={p[1]} r={14 * u * k} fill={theme.accent} stroke={theme.bg} strokeWidth={4 * u} />
							</g>
						);
					})}
				</svg>
			</AbsoluteFill>
			{points.map((pt, i) => {
				const k = appear(t, times[i] + 0.15, 0.6);
				const lp = labelPos[i];
				return (
					<div
						key={i}
						style={{
							position: 'absolute',
							left: lp.x * zoom + (width * (1 - zoom)) / 2,
							top: lp.y * zoom + (height * (1 - zoom)) / 2,
							transform: `translate(-50%, -50%) translateY(${(1 - k) * 12 * u}px)`,
							opacity: k,
							padding: `${10 * u}px ${24 * u}px`,
							borderRadius: 40 * u,
							background: theme.panel,
							border: `${2 * u}px solid ${alpha(theme.accent, 0.6)}`,
							fontFamily: theme.bodyFont,
							fontWeight: 700,
							fontSize: 38 * u,
							color: theme.text,
							whiteSpace: 'nowrap',
						}}
					>
						{pt.name}
					</div>
				);
			})}
			<div style={{position: 'absolute', top: 90 * u, width: '100%'}}>
				<InfoHeading text={scene.data.title} t={t} at={scene.start + 0.2} />
			</div>
		</AbsoluteFill>
	);
};
