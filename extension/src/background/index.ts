/**
 * Service worker: the only part that talks to the local server.
 * Content scripts can't reach http://127.0.0.1 from an https page and can't read cross-origin
 * images; the service worker can, thanks to host_permissions.
 */
import type { CaptureResponse, HealthResponse, Message, TabStatus, TranslateRequest, TranslateResponse } from '../shared/messages';
import { loadSettings } from '../shared/settings';
import { compareVersions } from '../shared/version';

/** chrome.tabs.captureVisibleTab allows 2 calls per second. */
const CAPTURE_INTERVAL_MS = 550;

class FetchError extends Error {}

/** Lost when the service worker sleeps; the content script re-reports on the next change. */
const tabStatus = new Map<number, TabStatus>();
chrome.tabs.onRemoved.addListener((tabId) => tabStatus.delete(tabId));

chrome.runtime.onMessage.addListener((msg: Message, sender, sendResponse) => {
  switch (msg.type) {
    case 'translate':
      translate(msg).then(sendResponse, (err: unknown) =>
        sendResponse({ ok: false, error: errorText(err), code: err instanceof FetchError ? 'fetch' : undefined }),
      );
      return true; // async response
    case 'capture':
      capture(sender).then(sendResponse, (err: unknown) => sendResponse({ ok: false, error: errorText(err) }));
      return true;
    case 'health':
      health().then(sendResponse);
      return true;
    case 'status':
      if (sender.tab?.id !== undefined) {
        const previous = tabStatus.get(sender.tab.id);
        // Keep the last error until the tab has no errors left, so the popup can explain the red badge
        const lastError = msg.lastError ?? (msg.errors > 0 ? previous?.lastError : undefined);
        tabStatus.set(sender.tab.id, { pending: msg.pending, errors: msg.errors, done: msg.done, waiting: msg.waiting, lastError });
        setBadge(sender.tab.id, msg.pending, msg.errors);
      }
      return false;
    case 'tab-status':
      sendResponse(tabStatus.get(msg.tabId) ?? { pending: 0, errors: 0 });
      return false;
  }
});

async function translate(req: TranslateRequest): Promise<TranslateResponse> {
  const { serverUrl } = await loadSettings();
  const image = req.image.kind === 'url' ? await fetchImage(req.image.url, req.pageUrl) : base64ToBlob(req.image.base64, req.image.mime);

  const form = new FormData();
  form.append('image', image, 'page');
  form.append('lang', req.lang);
  form.append('context_key', req.contextKey);
  form.append('title_key', req.titleKey);
  form.append('priority', String(req.priority));
  if (req.fresh) form.append('fresh', '1');

  let resp: Response;
  try {
    resp = await serverFetch(`${serverUrl}/translate`, { method: 'POST', body: form });
  } catch {
    throw new Error(`Сервер Oblachko не отвечает (${serverUrl}). Он запущен?`);
  }
  if (resp.status === 415) return { ok: false, code: 'skip', error: 'не картинка страницы' };
  if (!resp.ok) {
    const detail = await resp.json().then((j: { detail?: string }) => j.detail, () => resp.statusText);
    throw new Error(`Сервер: ${resp.status} ${detail ?? ''}`.trim());
  }
  return { ok: true, result: await resp.json() };
}

/** Delays before retrying a request to the local server that failed at the network level. */
const SERVER_RETRY_MS = [500, 1500, 4000];

/**
 * fetch() to the local server that rides out short outages (server restarting, a busy moment):
 * network errors are retried, HTTP errors are returned as they are.
 */
async function serverFetch(url: string, init?: RequestInit, retryMs: number[] = SERVER_RETRY_MS): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fetch(url, init);
    } catch (err) {
      if (attempt >= retryMs.length) throw err;
      await new Promise((resolve) => setTimeout(resolve, retryMs[attempt]));
    }
  }
}

async function fetchImage(url: string, pageUrl: string): Promise<Blob> {
  await setReferer(url, pageUrl);
  let resp: Response;
  try {
    resp = await fetch(url, { credentials: 'include' });
  } catch {
    throw new FetchError('Не удалось скачать картинку');
  }
  if (!resp.ok) throw new FetchError(`Не удалось скачать картинку: HTTP ${resp.status}`);
  const blob = await resp.blob();
  // Anti-hotlink setups answer 200 with an HTML page or a tiny placeholder
  if (blob.type.startsWith('text/') || blob.size < 2048) throw new FetchError('CDN отдал не картинку');
  return blob;
}

const refererByHost = new Map<string, string>();

/**
 * fetch() can't set Referer, and without it many image CDNs refuse the download. A session rule
 * sets it for requests to that host that come from no tab, i.e. from this service worker only.
 */
async function setReferer(url: string, pageUrl: string): Promise<void> {
  const host = new URL(url).hostname;
  const referer = pageUrl.split('#')[0];
  if (refererByHost.get(host) === referer) return;
  const id = ruleId(host);
  await chrome.declarativeNetRequest.updateSessionRules({
    removeRuleIds: [id],
    addRules: [
      {
        id,
        priority: 1,
        action: {
          type: chrome.declarativeNetRequest.RuleActionType.MODIFY_HEADERS,
          requestHeaders: [{ header: 'referer', operation: chrome.declarativeNetRequest.HeaderOperation.SET, value: referer }],
        },
        condition: {
          requestDomains: [host],
          tabIds: [chrome.tabs.TAB_ID_NONE],
          resourceTypes: [chrome.declarativeNetRequest.ResourceType.XMLHTTPREQUEST],
        },
      },
    ],
  });
  refererByHost.set(host, referer);
}

function ruleId(host: string): number {
  let hash = 0;
  for (const ch of host) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return (hash % 1_000_000) + 1;
}

let captureQueue: Promise<unknown> = Promise.resolve();
let lastCapture = 0;

/** Screenshots are rate-limited by Chrome, so they queue up here. */
function capture(sender: chrome.runtime.MessageSender): Promise<CaptureResponse> {
  const job = captureQueue.then(async (): Promise<CaptureResponse> => {
    const tab = sender.tab;
    if (!tab?.active) return { ok: false, error: 'Вкладка не активна' };
    const wait = lastCapture + CAPTURE_INTERVAL_MS - Date.now();
    if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
    lastCapture = Date.now();
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
    return { ok: true, dataUrl };
  });
  captureQueue = job.catch(() => {});
  return job;
}

function base64ToBlob(base64: string, mime: string): Blob {
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

async function health(): Promise<HealthResponse> {
  const { serverUrl } = await loadSettings();
  let result: HealthResponse;
  try {
    // Generous timeout: a PC busy with OCR and the LLM can be slow to answer. One retry only, so the
    // popup doesn't hang when the server really is off
    const resp = await serverFetch(`${serverUrl}/health`, { signal: AbortSignal.timeout(10000) }, [500]);
    result = resp.ok ? await resp.json() : { ok: false, error: `HTTP ${resp.status}` };
  } catch {
    return { ok: false, error: `Сервер не отвечает (${serverUrl})` };
  }
  if (result.version) await reloadIfOutdated(result.version);
  return result;
}

/**
 * The updater (start.bat) replaces the unpacked extension's files on disk together with the server;
 * Chrome only picks them up on reload. When the server is newer, reload once for that version:
 * if the files didn't change (extension loaded from another folder), the popup explains instead.
 */
async function reloadIfOutdated(serverVersion: string): Promise<void> {
  if (compareVersions(serverVersion, chrome.runtime.getManifest().version) <= 0) return;
  const self = await chrome.management.getSelf();
  if (self.installType !== 'development') return;
  const { reloadedFor } = await chrome.storage.local.get('reloadedFor');
  if (reloadedFor === serverVersion) return;
  await chrome.storage.local.set({ reloadedFor: serverVersion });
  chrome.runtime.reload();
}

// Service workers start often (every page message); a cheap moment to notice an update
void health();

function setBadge(tabId: number, pending: number, errors: number): void {
  const text = pending > 0 ? String(pending) : errors > 0 ? '!' : '';
  chrome.action.setBadgeText({ tabId, text }).catch(() => {}); // tab may be gone
  chrome.action.setBadgeBackgroundColor({ tabId, color: errors > 0 && pending === 0 ? '#d93025' : '#5b6ee1' }).catch(() => {});
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
