import type { ImagePayload } from '../shared/messages';

/**
 * How to get the page bytes to the service worker.
 * blob:/data:/same-origin images are readable here (MangaDex serves pages as blob: URLs that only
 * exist inside the page), so we read them and send the bytes. Anything else is a cross-origin CDN
 * (klmanga): the service worker downloads it itself, host permissions let it past CORS.
 */
export async function imagePayload(src: string): Promise<ImagePayload> {
  const url = new URL(src, location.href);
  if (url.protocol === 'blob:' || url.protocol === 'data:' || url.origin === location.origin) {
    const blob = await (await fetch(url)).blob();
    return { kind: 'data', base64: await blobToBase64(blob), mime: blob.type || 'application/octet-stream' };
  }
  return { kind: 'url', url: url.href };
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(',', 2)[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}
