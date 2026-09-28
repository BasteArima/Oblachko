import { backgroundImage, backgroundPlacement } from './background-image';

/**
 * A manga page on screen: an <img>, a <canvas> the reader draws into, or any other element
 * that shows the page as its CSS background-image.
 */
export type PageElement = HTMLElement;

export function naturalSize(el: PageElement): [number, number] {
  if (el instanceof HTMLImageElement) return [el.naturalWidth, el.naturalHeight];
  if (el instanceof HTMLCanvasElement) return [el.width, el.height];
  const img = backgroundImage(el);
  return img ? [img.naturalWidth, img.naturalHeight] : [0, 0];
}

/**
 * On-screen rect of the element's picture: content box of an <img>/<canvas> honouring object-fit
 * (readers use contain to fit the viewport), or the drawn area of a background image.
 */
export function contentRect(el: PageElement): DOMRect {
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.bottom < -innerHeight || rect.top > 2 * innerHeight) return rect;
  const style = getComputedStyle(el);
  const [nw, nh] = naturalSize(el);
  const border = (side: 'Left' | 'Right' | 'Top' | 'Bottom') => parseFloat(style[`border${side}Width`]);
  const padding = (side: 'Left' | 'Right' | 'Top' | 'Bottom') => parseFloat(style[`padding${side}`]);

  if (!(el instanceof HTMLImageElement) && !(el instanceof HTMLCanvasElement)) {
    // Backgrounds are laid out in the padding box
    const left = rect.left + border('Left');
    const top = rect.top + border('Top');
    const width = rect.width - border('Left') - border('Right');
    const height = rect.height - border('Top') - border('Bottom');
    if (!nw || !nh) return new DOMRect(left, top, width, height);
    const drawn = backgroundPlacement(style, nw, nh, width, height);
    return new DOMRect(left + drawn.x, top + drawn.y, drawn.width, drawn.height);
  }

  const left = rect.left + border('Left') + padding('Left');
  const top = rect.top + border('Top') + padding('Top');
  const width = rect.width - border('Left') - border('Right') - padding('Left') - padding('Right');
  const height = rect.height - border('Top') - border('Bottom') - padding('Top') - padding('Bottom');
  if ((style.objectFit === 'contain' || style.objectFit === 'scale-down') && nw && nh) {
    const scale = Math.min(width / nw, height / nh, style.objectFit === 'scale-down' ? 1 : Infinity);
    const w = nw * scale;
    const h = nh * scale;
    return new DOMRect(left + (width - w) / 2, top + (height - h) / 2, w, h);
  }
  return new DOMRect(left, top, width, height);
}

/** Whole picture inside the viewport: the only case a tab screenshot can stand in for the pixels. */
export function fullyVisible(el: PageElement): boolean {
  const r = contentRect(el);
  return r.width > 0 && r.height > 0 && r.top >= -2 && r.left >= -2 && r.bottom <= innerHeight + 2 && r.right <= innerWidth + 2;
}
