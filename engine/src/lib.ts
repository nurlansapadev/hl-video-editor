import {createContext, useContext} from 'react';
import {Easing, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {defaultTheme} from './theme';
import type {Plan, Theme} from './types';

export const PlanContext = createContext<{plan: Plan; theme: Theme}>({
	plan: {version: 1, fps: 30, width: 1920, height: 1080, duration: 1, scenes: []},
	theme: defaultTheme,
});

// Кадр, с которого начинается текущая Sequence (чтобы внутри считать абсолютное время ролика)
export const SceneFromContext = createContext<number>(0);

export const usePlan = () => useContext(PlanContext);
export const useTheme = () => useContext(PlanContext).theme;

/** Абсолютное время ролика в секундах (с учётом смещения Sequence). */
export const useTime = (): number => {
	const frame = useCurrentFrame();
	const from = useContext(SceneFromContext);
	const {fps} = useVideoConfig();
	return (frame + from) / fps;
};

/** Единица размера: 1 = 1px при высоте 1080 (для вертикали — по ширине). */
export const useUnit = (): number => {
	const {width, height} = useVideoConfig();
	return Math.min(width, height) / 1080;
};

export const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));

export const smooth = Easing.bezier(0.45, 0, 0.25, 1);
export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);
export const gentle = Easing.inOut(Easing.sin);

/** Плавное появление: 0 → 1 за dur секунд, начиная с at. */
export const appear = (t: number, at: number, dur = 0.6, ease = easeOut) => ease(clamp((t - at) / dur));

/** Появление и исчезновение элемента в окне [start, end]. */
export const window01 = (t: number, start: number, end: number, fadeIn = 0.5, fadeOut = 0.4) =>
	Math.min(easeOut(clamp((t - start) / fadeIn)), smooth(clamp((end - t) / fadeOut)));

/** Путь к файлу проекта (папка проекта подключается как public-dir). */
export const asset = (src: string) => (/^(https?:|data:|blob:)/.test(src) ? src : staticFile(src.replace(/\\/g, '/')));

// Разделители чисел по языку ролика: ru/es — «6 000 000,5», en — «6,000,000.5»
let NUM_GROUP = ' ';
let NUM_DEC = ',';
export const setNumberLocale = (lang?: string) => {
	NUM_GROUP = lang === 'en' ? ',' : lang === 'es' || lang === 'de' ? '.' : lang === 'fr' ? '\u202f' : ' ';
	NUM_DEC = lang === 'en' ? '.' : ',';
};

/** Число с разделителями разрядов: 6 000 000 (ru), 6,000,000 (en) */
export const formatNumber = (v: number, decimals = 0) => {
	const fixed = v.toFixed(decimals);
	const [int, frac] = fixed.split('.');
	const spaced = int.replace(/\B(?=(\d{3})+(?!\d))/g, NUM_GROUP);
	return frac ? `${spaced}${NUM_DEC}${frac}` : spaced;
};
