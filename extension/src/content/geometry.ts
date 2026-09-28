/** Page images come as <img> or, in some readers, as a <canvas> the page draws into. */
export type PageElement = HTMLImageElement | HTMLCanvasElement;

export function naturalSize(el: PageElement): [number, number] {
  return el instanceof HTMLImageElement ? [el.naturalWidth, el.naturalHeight] : [el.width, el.height];
}

/** On-screen rect of the element's picture, honouring object-fit: contain (readers use it to fit the viewport). */
export function contentRect(el: PageElement): DOMRect {
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.bottom < -innerHeight || rect.top > 2 * innerHeight) return rect;
  const style = getComputedStyle(el);
  const left = rect.left + parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft);
  const top = rect.top + parseFloat(style.borderTopWidth) + parseFloat(style.paddingTop);
  const width = rect.width - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth) - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  const height = rect.height - parseFloat(style.borderTopWidth) - parseFloat(style.borderBottomWidth) - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);

  const [nw, nh] = naturalSize(el);
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
