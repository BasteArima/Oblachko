import type { GlossaryEntry, HealthResponse, PageInfo, TabStatus } from '../shared/messages';
import { loadSettings, siteKey, siteSettings, updateServerUrl, updateSite, type Lang } from '../shared/settings';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

const statusEl = $<HTMLParagraphElement>('status');
const dot = $<HTMLSpanElement>('status-dot');
const enabled = $<HTMLInputElement>('enabled');
const lang = $<HTMLSelectElement>('lang');
const serverUrl = $<HTMLInputElement>('server-url');
const glossaryRows = $<HTMLDivElement>('glossary-rows');
const glossaryStatus = $<HTMLParagraphElement>('glossary-status');

async function init(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const url = tab?.url ? new URL(tab.url) : null;
  const host = url && /^https?:$/.test(url.protocol) ? siteKey(url.hostname) : null;

  if (host && tab?.id !== undefined) {
    $('host').textContent = host;
    const site = await siteSettings(host);
    enabled.checked = site.enabled;
    lang.value = site.lang;
    enabled.addEventListener('change', () => updateSite(host, { enabled: enabled.checked }));
    lang.addEventListener('change', () => updateSite(host, { lang: lang.value as Lang }));
    void showTabError(tab.id);
    void initGlossary(tab.id);
  } else {
    $('site-section').hidden = true;
    $('unsupported').hidden = false;
  }

  serverUrl.value = (await loadSettings()).serverUrl;
  $<HTMLFormElement>('server-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    await updateServerUrl(serverUrl.value);
    void checkHealth();
  });

  void checkHealth();
}

async function checkHealth(): Promise<void> {
  statusEl.textContent = 'Проверяю сервер…';
  dot.className = 'dot';
  const health: HealthResponse = await chrome.runtime.sendMessage({ type: 'health' });

  if (!health.ok) {
    dot.className = 'dot bad';
    statusEl.textContent = `${health.error ?? 'Сервер недоступен'}. Запустите сервер Oblachko.`;
  } else if (!health.llm?.ok) {
    dot.className = 'dot bad';
    statusEl.textContent = `Сервер работает, но LLM недоступна: ${health.llm?.error ?? health.llm?.url}`;
  } else {
    dot.className = 'dot ok';
    const gpu = health.device?.startsWith('CUDA') ? 'GPU' : 'CPU';
    const queue = health.queue ? ` · в очереди ${health.queue}` : '';
    statusEl.textContent = `Готов · ${health.llm.model} · ${gpu}${queue}`;
  }
}

async function showTabError(tabId: number): Promise<void> {
  const status: TabStatus = await chrome.runtime.sendMessage({ type: 'tab-status', tabId });
  if (!status.lastError) return;
  const el = $<HTMLParagraphElement>('tab-error');
  el.textContent = `Ошибок на странице: ${status.errors}. Последняя: ${status.lastError}`;
  el.hidden = false;
}

// --- Name glossary of the title open in the tab ---

let glossaryTitle = '';

async function initGlossary(tabId: number): Promise<void> {
  let info: PageInfo;
  try {
    info = await chrome.tabs.sendMessage(tabId, { type: 'page-info' });
  } catch {
    return; // no content script: page opened before the extension was installed or reloaded
  }
  glossaryTitle = info.titleKey;
  $('glossary').hidden = false;
  $('glossary-add').addEventListener('click', () => addRow({ src: '', dst: '' }, true).querySelector('input')!.focus());
  $<HTMLFormElement>('glossary-form').addEventListener('submit', (e) => {
    e.preventDefault();
    void saveGlossary();
  });
  try {
    renderGlossary(await glossaryRequest('GET'));
  } catch {
    glossaryStatus.textContent = 'Сервер недоступен.';
  }
}

async function glossaryRequest(method: 'GET' | 'PUT', entries?: GlossaryEntry[]): Promise<GlossaryEntry[]> {
  const { serverUrl: base } = await loadSettings();
  const resp =
    method === 'GET'
      ? await fetch(`${base}/glossary?title=${encodeURIComponent(glossaryTitle)}`)
      : await fetch(`${base}/glossary`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: glossaryTitle, entries }),
        });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()).entries;
}

function renderGlossary(entries: GlossaryEntry[]): void {
  glossaryRows.replaceChildren();
  entries.forEach((entry) => addRow(entry, false));
  $('glossary-count').textContent = entries.length ? `(${entries.length})` : '';
  if (!entries.length) glossaryStatus.textContent = 'Пока пусто: имена появятся после перевода первых страниц.';
}

/** Source names come from OCR and stay read-only; manually added rows can set both sides. */
function addRow(entry: GlossaryEntry, editableSource: boolean): HTMLDivElement {
  const row = document.createElement('div');
  row.className = 'name-row';
  const src = Object.assign(document.createElement('input'), { value: entry.src, readOnly: !editableSource, placeholder: 'Оригинал' });
  const arrow = Object.assign(document.createElement('span'), { textContent: '→' });
  const dst = Object.assign(document.createElement('input'), { value: entry.dst, placeholder: 'По-русски' });
  const remove = Object.assign(document.createElement('button'), { type: 'button', className: 'remove', textContent: '✕', title: 'Удалить' });
  src.title = entry.manual ? 'Исправлено вручную' : 'Запомнено автоматически';
  remove.addEventListener('click', () => row.remove());
  row.append(src, arrow, dst, remove);
  glossaryRows.append(row);
  glossaryStatus.textContent = '';
  return row;
}

async function saveGlossary(): Promise<void> {
  const entries = [...glossaryRows.querySelectorAll('.name-row')]
    .map((row) => {
      const [src, dst] = row.querySelectorAll('input');
      return { src: src.value.trim(), dst: dst.value.trim() };
    })
    .filter((e) => e.src && e.dst);
  try {
    renderGlossary(await glossaryRequest('PUT', entries));
    glossaryStatus.textContent = 'Сохранено. Обновите страницу, чтобы перевести её с новыми именами.';
  } catch {
    glossaryStatus.textContent = 'Не удалось сохранить: сервер недоступен.';
  }
}

void init();
