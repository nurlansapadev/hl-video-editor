// Шрифты лежат внутри движка (кириллица включена), интернет при рендере не нужен.
import '@fontsource/montserrat/cyrillic-500.css';
import '@fontsource/montserrat/cyrillic-600.css';
import '@fontsource/montserrat/cyrillic-700.css';
import '@fontsource/montserrat/cyrillic-800.css';
import '@fontsource/montserrat/latin-500.css';
import '@fontsource/montserrat/latin-600.css';
import '@fontsource/montserrat/latin-700.css';
import '@fontsource/montserrat/latin-800.css';
import '@fontsource/fredoka/latin-500.css';
import '@fontsource/fredoka/latin-600.css';
import '@fontsource/fredoka/latin-700.css';
import '@fontsource/fredoka/latin-ext-600.css';
import '@fontsource/fredoka/latin-ext-700.css';
import '@fontsource/ibm-plex-mono/cyrillic-500.css';
import '@fontsource/ibm-plex-mono/cyrillic-600.css';
import '@fontsource/ibm-plex-mono/latin-500.css';
import '@fontsource/ibm-plex-mono/latin-600.css';
import '@fontsource/playfair-display/cyrillic-600.css';
import '@fontsource/playfair-display/cyrillic-700.css';
import '@fontsource/playfair-display/cyrillic-600-italic.css';
import '@fontsource/playfair-display/latin-600.css';
import '@fontsource/playfair-display/latin-700.css';
import '@fontsource/playfair-display/latin-600-italic.css';
import {continueRender, delayRender} from 'remotion';

const handle = delayRender('Загрузка шрифтов');
const families = [
	'500 1em Montserrat', '600 1em Montserrat', '700 1em Montserrat', '800 1em Montserrat',
	'600 1em "Playfair Display"', '700 1em "Playfair Display"', 'italic 600 1em "Playfair Display"',
	'500 1em Fredoka', '600 1em Fredoka', '700 1em Fredoka',
	'500 1em "IBM Plex Mono"', '600 1em "IBM Plex Mono"',
];
Promise.all(families.map((f) => document.fonts.load(f, 'АаЯя Aa 0123 ñáé¿¡')))
	.then(() => continueRender(handle))
	.catch(() => continueRender(handle));
