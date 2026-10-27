// План монтажа (plan.json). Все времена — в секундах от начала ролика.

export type TransitionType = 'cut' | 'fade' | 'dip' | 'push' | 'zoom' | 'wipe' | 'blur';
export type Direction = 'left' | 'right' | 'up' | 'down';

export type Transition = {
	type: TransitionType;
	duration?: number; // сек, по умолчанию 0.8
	direction?: Direction; // для push / wipe
};

export type Framing = {scale: number; x: number; y: number}; // x,y — сдвиг в % кадра

export type Motion = {
	type:
		| 'none'
		| 'zoomIn'
		| 'zoomOut'
		| 'panLeft'
		| 'panRight'
		| 'panUp'
		| 'panDown'
		| 'custom';
	strength?: number; // 1 = стандартно, 0.5 = мягче, 1.5 = сильнее
	focus?: {x: number; y: number}; // точка фокуса для зума, 0..1
	from?: Framing;
	to?: Framing;
};

export type Punch = {
	at: number; // момент акцентного приближения
	scale?: number; // 1.12 по умолчанию
	duration?: number; // длительность наезда, 0.6
	focus?: {x: number; y: number};
};

export type Overlay =
	| {type: 'lowerThird'; start: number; end: number; title: string; subtitle?: string}
	| {type: 'label'; start: number; end: number; text: string; position?: 'top' | 'center' | 'bottom'}
	| {type: 'date'; start: number; end: number; text: string};

export type Background = {
	src?: string; // картинка/видео фоном (размывается)
	mediaType?: 'image' | 'video';
	blur?: number;
	dim?: number; // 0..1 затемнение
};

type SceneBase = {
	id: string;
	start: number;
	end: number;
	transition?: Transition; // переход В эту сцену
	overlays?: Overlay[];
	captions?: boolean; // показывать ли субтитры поверх этой сцены (по умолчанию: да)
	note?: string; // комментарий режиссёра, не рендерится
};

export type MediaScene = SceneBase & {
	kind: 'media';
	src: string;
	mediaType: 'image' | 'video';
	fit?: 'cover' | 'blurfill' | 'inset'; // blurfill — для вертикальных/квадратных кадров; inset — низкое разрешение: кадр в рамке на фоне
	blurSrc?: string; // заранее размытая копия для blurfill
	motion?: Motion;
	punches?: Punch[];
	videoStart?: number; // с какой секунды исходника начинать
	videoRate?: number; // скорость воспроизведения
	videoVolume?: number; // 0 = без звука (по умолчанию)
	srcDuration?: number; // длительность исходного видео
	srcAspect?: number; // пропорции исходника (для рамки inset)
	badge?: SourceBadge; // «Архивные кадры · NASA», «Фото: автор / Wikimedia Commons»
};

export type SourceBadge = {label?: string; source?: string};

export type CollageItem = {src: string; mediaType: 'image' | 'video'; at?: number; badge?: SourceBadge; duration?: number};

// Документальный коллаж: несколько кадров на одном экране
export type CollageScene = SceneBase & {
	kind: 'collage';
	layout: 'mosaic' | 'board' | 'split';
	items: CollageItem[];
};

export type TimelineItem = {label: string; title?: string; at?: number};
export type ListItem = {text: string; detail?: string; at?: number};
export type MapPoint = {name: string; lon: number; lat: number; at?: number};
export type BarItem = {label: string; value: number; at?: number; display?: string; from?: number; fromDisplay?: string};

export type InfographicScene = SceneBase & {background?: Background} & (
		| {kind: 'title'; data: {title: string; subtitle?: string; kicker?: string; variant?: 'hero' | 'number' | 'side' | 'tracking' | 'split' | 'quote'; number?: number; of?: number}}
		| {kind: 'timeline'; data: {title?: string; items: TimelineItem[]}}
		| {kind: 'list'; data: {title?: string; items: ListItem[]; numbered?: boolean}}
		| {kind: 'counter'; data: {value: number; prefix?: string; suffix?: string; label?: string; decimals?: number; at?: number}}
		| {kind: 'quote'; data: {text: string; author?: string}}
		| {kind: 'map'; data: {title?: string; points: MapPoint[]; route?: boolean; region?: [number, number, number, number]; highlight?: string[]}}
		| {kind: 'bars'; data: {title?: string; items: BarItem[]; unit?: string; source?: string; legend?: [string, string] | string[]}}
		| {kind: 'outro'; data: {title?: string; question?: string; cta?: string}}
	);

export type Scene = MediaScene | InfographicScene | CollageScene;

export type CaptionWord = {text: string; start: number; end: number};
export type CaptionCue = {start: number; end: number; lines: string[]; words?: CaptionWord[]};

export type MusicTrack = {
	src: string;
	volume?: number; // уровень без голоса, 0.25
	duckVolume?: number; // уровень под голосом, 0.07
	start?: number;
	end?: number;
	fadeIn?: number;
	fadeOut?: number;
	duck?: [number, number][]; // интервалы речи
	open?: [number, number][]; // где голоса нет совсем (заставка, концовка) — музыка звучит в полную силу
	openVolume?: number; // уровень на заставке и в концовке, 0.6
};

export type Sfx = {src: string; at: number; volume?: number};

export type Theme = {
	style?: 'documentary' | 'cartoon'; // cartoon — светлый бумажный фон для инфографики
	decor?: 'blueprint' | 'editorial' | 'minimal'; // оформление: чертёж (уголки, линейка, сетка) / журнал (тонкие линии) / минимализм
	bg: string;
	panel: string;
	text: string;
	muted: string;
	accent: string;
	accent2: string;
	headingFont: string;
	bodyFont: string;
	monoFont?: string; // служебные подписи: глава, дата, источник, цифры на схемах
	grain?: number; // плёночное зерно поверх кадра, 0..0.2
	captionSize: number; // px при высоте 1080
	captionBg: string;
	captionHighlight: string | null; // подсветка текущего слова, null — выключено
	vignette: number; // 0..1
	grade: string; // CSS filter для медиа
};

export type Plan = {
	version: 1;
	language?: string; // ru / es / en — формат чисел
	fps: number;
	width: number;
	height: number;
	duration: number;
	theme?: Partial<Theme>;
	defaultTransition?: Transition;
	voice?: {src: string; volume?: number; offset?: number};
	music?: MusicTrack[];
	sfx?: Sfx[];
	captions?: {enabled: boolean; cues: CaptionCue[]};
	paper?: string; // текстура бумаги поверх мультсцен
	scenes: Scene[];
};
