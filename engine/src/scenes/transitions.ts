import type React from 'react';
import {clamp, smooth} from '../lib';
import type {Transition} from '../types';

export const DEFAULT_DURATION = 0.8;

export const transitionDuration = (t?: Transition) =>
	!t || t.type === 'cut' ? 0 : Math.max(0.1, t.duration ?? DEFAULT_DURATION);

const shift = (dir: Transition['direction'], amount: number) => {
	switch (dir ?? 'left') {
		case 'left':
			return `translateX(${amount}%)`;
		case 'right':
			return `translateX(${-amount}%)`;
		case 'up':
			return `translateY(${amount}%)`;
		case 'down':
			return `translateY(${-amount}%)`;
	}
};

/** Стиль входящей сцены. p — прогресс перехода 0..1 */
export const enterStyle = (tr: Transition, pRaw: number): React.CSSProperties => {
	const p = smooth(clamp(pRaw));
	switch (tr.type) {
		case 'fade':
			return {opacity: p};
		case 'dip':
			return {opacity: clamp((pRaw - 0.5) * 2)};
		case 'push':
			return {transform: shift(tr.direction, (1 - p) * 100)};
		case 'zoom':
			return {opacity: p, transform: `scale(${1.12 - 0.12 * p})`};
		case 'blur':
			return {opacity: p, filter: `blur(${(1 - p) * 24}px)`};
		case 'wipe': {
			const pos = p * 130 - 15; // мягкий край 15%
			const dir = tr.direction ?? 'left';
			const angle = dir === 'left' ? 'to left' : dir === 'right' ? 'to right' : dir === 'up' ? 'to top' : 'to bottom';
			const mask = `linear-gradient(${angle}, black ${pos - 15}%, transparent ${pos + 15}%)`;
			return {WebkitMaskImage: mask, maskImage: mask};
		}
		default:
			return {};
	}
};

/** Стиль уходящей сцены (под входящей). */
export const exitStyle = (tr: Transition, pRaw: number): React.CSSProperties => {
	const p = smooth(clamp(pRaw));
	switch (tr.type) {
		case 'dip':
			return {opacity: clamp(1 - pRaw * 2)};
		case 'push':
			return {transform: shift(tr.direction, -p * 100)};
		case 'zoom':
			return {transform: `scale(${1 + 0.06 * p})`};
		case 'blur':
			return {filter: `blur(${p * 24}px)`};
		default:
			return {};
	}
};
