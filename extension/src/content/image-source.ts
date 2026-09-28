/**
 * Getting page pixels to the service worker, cheapest way first:
 * 1. blob:/data:/same-origin <img> - read here (MangaDex pages are blob: URLs that only exist in the page)
 * 2. cross-origin <img> - the service worker downloads the URL itself, host permissions get it past CORS
 * 3. readable <canvas> - toBlob
 * 4. anything else (tainted canvas, CDN refusing the download) - crop from a screenshot of the tab
 */
import type { CaptureResponse, ImagePayload } from '../shared/messages';
import { contentRect, type PageElement } from './geometry';

export class NotVisibleError extends Error {}

/** null = the pixels can't be read from the page, a screenshot is needed. */
export async function readPixels(el: PageElement): Promise<ImagePayload | null> {
  if (el instanceof HTMLCanvasElement) {
    let blob: Blob | null;
    try {
      blob = await new Promise<Blob | null>((resolve) => el.toBlob(resolve, 'image/png'));
    } catch {
      return null; // SecurityError: canvas tainted by cross-origin images
    }
    return blob ? blobPayload(blob) : null;
  }

  const url = new URL(el.currentSrc || el.src, location.href);
  if (url.protocol === 'blob:' || url.protocol === 'data:' || url.origin === location.origin) {
    return blobPayload(await (await fetch(url)).blob());
  }
  return { kind: 'url', url: url.href };
}

/**
 * Crops the element out of a screenshot of the visible tab. The element must be fully on screen;
 * our own overlay is hidden for the moment of the capture so it doesn't end up in the picture.
 */
export async function capturePixels(el: PageElement, setOverlayHidden: (hidden: boolean) => void): Promise<ImagePayload> {
  let rect = contentRect(el);
  setOverlayHidden(true);
  let response: CaptureResponse;
  try {
    await nextFrame();
    await nextFrame();
    rect = contentRect(el); // may have moved while we waited
    if (rect.top < -2 || rect.bottom > innerHeight + 2) throw new NotVisibleError();
    response = await chrome.runtime.sendMessage({ type: 'capture' });
  } finally {
    setOverlayHidden(false);
  }
  if (!response.ok) throw new Error(response.error);

  const shot = await createImageBitmap(dataUrlToBlob(response.dataUrl));
  const scale = shot.width / innerWidth; // device pixel ratio times page zoom
  const w = Math.round(rect.width * scale);
  const h = Math.round(rect.height * scale);
  const crop = new OffscreenCanvas(w, h);
  crop.getContext('2d')!.drawImage(shot, rect.left * scale, rect.top * scale, w, h, 0, 0, w, h);
  shot.close();
  return blobPayload(await crop.convertToBlob({ type: 'image/png' }));
}

/**
 * What the element currently shows, to notice page flips. Canvases get a tiny thumbnail
 * fingerprint; null when a tainted canvas can't be read at all.
 */
export function contentKey(el: PageElement): string | null {
  if (el instanceof HTMLImageElement) return el.currentSrc || el.src || null;
  try {
    const probe = document.createElement('canvas');
    probe.width = probe.height = 8;
    const ctx = probe.getContext('2d', { willReadFrequently: true })!;
    ctx.drawImage(el, 0, 0, 8, 8);
    return `canvas:${el.width}x${el.height}:${ctx.getImageData(0, 0, 8, 8).data.join(',')}`;
  } catch {
    return null;
  }
}

async function blobPayload(blob: Blob): Promise<ImagePayload> {
  return { kind: 'data', base64: await blobToBase64(blob), mime: blob.type || 'application/octet-stream' };
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(',', 2)[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

/** Decoded by hand: fetch(data:) can be blocked by the page's CSP. */
function dataUrlToBlob(dataUrl: string): Blob {
  const [header, base64 = ''] = dataUrl.split(',', 2);
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: /data:([^;]+)/.exec(header)?.[1] ?? 'image/png' });
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}
