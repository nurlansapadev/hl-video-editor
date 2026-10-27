import type {Theme} from './types';

// Фирменный дизайн-код «Инженерный чертёж» (см. components/Brand.tsx и DESIGN.md)
export const defaultTheme: Theme = {
	style: 'documentary',
	bg: '#0E1418', // тёмный графит
	panel: 'rgba(10, 16, 20, 0.84)',
	text: '#F2F5F7',
	muted: '#A9B6BF',
	accent: '#F2A541', // сигнальный оранжевый
	accent2: '#3FA7D6', // вода
	headingFont: 'Montserrat, "Segoe UI", Arial, sans-serif',
	bodyFont: 'Montserrat, "Segoe UI", Arial, sans-serif',
	monoFont: '"IBM Plex Mono", Consolas, monospace',
	captionSize: 54,
	captionBg: 'rgba(8, 12, 15, 0.68)',
	captionHighlight: null,
	vignette: 0.4,
	grade: 'contrast(1.05) saturate(1.02)',
	grain: 0.06,
};
