/** Pages drawn as a CSS background-image of some <div> instead of an <img>. */

const MAX_CACHED = 200;
/** Decoded copies of background images; the page already loaded them, so they come from the HTTP cache. */
const images = new Map<string, HTMLImageElement>();

/** Absolute URL of the element's background when it is exactly one url(), else null. */
export function backgroundUrl(el: Element): string | null {
  const match = /^url\("?(.+?)"?\)$/.exec(getComputedStyle(el).backgroundImage);
  return match ? new URL(match[1], location.href).href : null;
}

/** The decoded background image, or null while it's loading (onLoad fires once it's ready). */
export function backgroundImage(el: Element, onLoad?: () => void): HTMLImageElement | null {
  const url = backgroundUrl(el);
  if (!url) return null;
  let img = images.get(url);
  if (!img) {
    img = new Image();
    img.src = url;
    images.set(url, img);
    if (images.size > MAX_CACHED) images.delete(images.keys().next().value!);
  }
  if (img.complete && img.naturalWidth) return img;
  if (onLoad) img.addEventListener('load', onLoad, { once: true });
  return null;
}

/**
 * Where the background picture is drawn inside a padding box of width w and height h, from the
 * computed background-size and background-position (computed values are keywords, px or %).
 */
export function backgroundPlacement(style: CSSStyleDeclaration, nw: number, nh: number, w: number, h: number): DOMRect {
  let dw: number;
  let dh: number;
  const size = style.backgroundSize;
  if (size === 'contain' || size === 'cover') {
    const scale = (size === 'contain' ? Math.min : Math.max)(w / nw, h / nh);
    dw = nw * scale;
    dh = nh * scale;
  } else {
    const [sx = 'auto', sy = 'auto'] = size.split(' ');
    const lx = length(sx, w);
    const ly = length(sy, h);
    dw = lx ?? (ly !== null ? (ly * nw) / nh : nw);
    dh = ly ?? (lx !== null ? (lx * nh) / nw : nh);
  }
  const [px = '0%', py = '0%'] = style.backgroundPosition.split(' ');
  return new DOMRect(offset(px, w - dw), offset(py, h - dh), dw, dh);
}

function length(value: string, box: number): number | null {
  if (value.endsWith('%')) return (box * parseFloat(value)) / 100;
  if (value.endsWith('px')) return parseFloat(value);
  return null; // auto
}

function offset(value: string, free: number): number {
  if (value.endsWith('%')) return (free * parseFloat(value)) / 100;
  if (value.endsWith('px')) return parseFloat(value);
  return 0; // calc() and friends: rare enough to accept a misplaced overlay
}
