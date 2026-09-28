/**
 * Service worker: the only part that talks to the local server.
 * Content scripts can't reach http://127.0.0.1 from an https page and can't read cross-origin
 * images; the service worker can, thanks to host_permissions.
 */
import type { HealthResponse, Message, TranslateRequest, TranslateResponse } from '../shared/messages';
import { loadSettings } from '../shared/settings';

chrome.runtime.onMessage.addListener((msg: Message, sender, sendResponse) => {
  switch (msg.type) {
    case 'translate':
      translate(msg).then(sendResponse, (err: unknown) => sendResponse({ ok: false, error: errorText(err) }));
      return true; // async response
    case 'health':
      health().then(sendResponse);
      return true;
    case 'status':
      if (sender.tab?.id !== undefined) setBadge(sender.tab.id, msg.pending, msg.errors);
      return false;
  }
});

async function translate(req: TranslateRequest): Promise<TranslateResponse> {
  const { serverUrl } = await loadSettings();
  const image = req.image.kind === 'url' ? await fetchImage(req.image.url) : base64ToBlob(req.image.base64, req.image.mime);

  const form = new FormData();
  form.append('image', image, 'page');
  form.append('lang', req.lang);
  form.append('context_key', req.contextKey);
  form.append('priority', String(req.priority));

  let resp: Response;
  try {
    resp = await fetch(`${serverUrl}/translate`, { method: 'POST', body: form });
  } catch {
    throw new Error(`Сервер Oblachko не отвечает (${serverUrl}). Он запущен?`);
  }
  if (!resp.ok) {
    const detail = await resp.json().then((j: { detail?: string }) => j.detail, () => resp.statusText);
    throw new Error(`Сервер: ${resp.status} ${detail ?? ''}`.trim());
  }
  return { ok: true, result: await resp.json() };
}

async function fetchImage(url: string): Promise<Blob> {
  const resp = await fetch(url, { credentials: 'include' });
  if (!resp.ok) throw new Error(`Не удалось скачать картинку: ${resp.status}`);
  return resp.blob();
}

function base64ToBlob(base64: string, mime: string): Blob {
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

async function health(): Promise<HealthResponse> {
  const { serverUrl } = await loadSettings();
  try {
    const resp = await fetch(`${serverUrl}/health`, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) return { ok: false, error: `HTTP ${resp.status}` };
    return await resp.json();
  } catch {
    return { ok: false, error: `Сервер не отвечает (${serverUrl})` };
  }
}

function setBadge(tabId: number, pending: number, errors: number): void {
  const text = pending > 0 ? String(pending) : errors > 0 ? '!' : '';
  chrome.action.setBadgeText({ tabId, text }).catch(() => {}); // tab may be gone
  chrome.action.setBadgeBackgroundColor({ tabId, color: errors > 0 && pending === 0 ? '#d93025' : '#5b6ee1' }).catch(() => {});
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
