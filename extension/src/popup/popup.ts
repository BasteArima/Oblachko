import type { GlossaryEntry, HealthResponse, PageInfo, PopupToPage, TabStatus } from '../shared/messages';
import { loadSettings, siteKey, siteSettings, updateServerUrl, updateSite, type Lang } from '../shared/settings';
import { compareVersions } from '../shared/version';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

/** While the popup is open: how often to look at the tab's progress and at the server. */
const TAB_POLL_MS = 1000;
const HEALTH_POLL_OK_MS = 10_000;
const HEALTH_POLL_BAD_MS = 3000;

const enabled = $<HTMLInputElement>('enabled');
const lang = $<HTMLSelectElement>('lang');
const serverUrl = $<HTMLInputElement>('server-url');
const glossaryRows = $<HTMLDivElement>('glossary-rows');
const glossaryStatus = $<HTMLParagraphElement>('glossary-status');

let tabId: number | undefined;

async function init(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const url = tab?.url ? new URL(tab.url) : null;
  const host = url && /^https?:$/.test(url.protocol) ? siteKey(url.hostname) : null;

  if (host && tab?.id !== undefined) {
    tabId = tab.id;
    $('host').textContent = host;
    const site = await siteSettings(host);
    enabled.checked = site.enabled;
    lang.value = site.lang;
    enabled.addEventListener('change', async () => {
      await updateSite(host, { enabled: enabled.checked });
      setTimeout(() => void refreshPage(), 300); // the content script starts or stops on the storage change
    });
    lang.addEventListener('change', () => updateSite(host, { lang: lang.value as Lang }));
    initPageControls();
    await refreshPage();
    setInterval(() => void refreshPage(), TAB_POLL_MS);
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

  $('recheck').addEventListener('click', () => void checkHealth());
  $('health-retry').addEventListener('click', () => void checkHealth());
  void checkHealth();
}

// --- Server and model ---

let healthTimer = 0;
let checking = false;
/** The page's errors repeat the server/model problem shown above: no need to say it twice */
let healthProblem: string | null = null;

async function checkHealth(): Promise<void> {
  if (checking) return;
  checking = true;
  clearTimeout(healthTimer);
  $('recheck').classList.add('spinning');
  $<HTMLButtonElement>('health-retry').disabled = true;
  let health: HealthResponse;
  try {
    health = await chrome.runtime.sendMessage({ type: 'health' });
  } catch (err) {
    health = { ok: false, error: String(err) };
  } finally {
    checking = false;
    $('recheck').classList.remove('spinning');
    $<HTMLButtonElement>('health-retry').disabled = false;
  }
  showHealth(health);
  const allGood = health.ok && health.llm?.ok;
  healthTimer = window.setTimeout(() => void checkHealth(), allGood ? HEALTH_POLL_OK_MS : HEALTH_POLL_BAD_MS);
}

function showHealth(health: HealthResponse): void {
  const serverDot = $('server-dot');
  const llmDot = $('llm-dot');
  let problem: Problem | null = null;

  if (!health.ok) {
    serverDot.className = 'dot bad';
    $('server-text').textContent = 'не отвечает';
    llmDot.className = 'dot';
    $('llm-text').textContent = '—';
    problem = explain(health.error ?? '', 'server');
  } else {
    serverDot.className = 'dot ok';
    const gpu = health.device?.startsWith('CUDA') ? 'GPU' : 'CPU';
    const queue = health.queue ? ` · очередь ${health.queue}` : '';
    $('server-text').textContent = `работает · ${gpu}${queue}`;
    $('server-text').title = health.device ?? '';
    if (health.llm?.ok) {
      llmDot.className = 'dot ok';
      $('llm-text').textContent = health.llm.model ?? 'готова';
      $('llm-text').title = health.llm.model ?? '';
    } else {
      llmDot.className = 'dot bad';
      $('llm-text').textContent = 'недоступна';
      problem = explain(health.llm?.error ?? '', 'llm');
    }
  }

  showProblem('health', problem);
  healthProblem = problem?.title ?? null;

  // The service worker reloads itself after an update; if it's still older, it was loaded from another folder
  const own = chrome.runtime.getManifest().version;
  const hint = $<HTMLParagraphElement>('version-hint');
  hint.hidden = !(health.version && compareVersions(health.version, own) > 0);
  if (!hint.hidden) {
    hint.textContent = `Сервер обновлён до ${health.version}, а расширение ещё ${own}. Откройте chrome://extensions и нажмите ↻ у Oblachko (расширение должно быть загружено из папки extension рядом с start.bat).`;
  }
}

// --- What the page does ---

function initPageControls(): void {
  $('retry-errors').addEventListener('click', () => void sendToPage({ type: 'retry-errors' }));
  $('retranslate').addEventListener('click', () => void sendToPage({ type: 'retranslate', fresh: true }));
  $('original').addEventListener('click', () => {
    const on = $('original').getAttribute('aria-pressed') !== 'true';
    $('original').setAttribute('aria-pressed', String(on));
    void sendToPage({ type: 'set-original', on });
  });
}

let glossaryStarted = false;

async function refreshPage(): Promise<void> {
  if (tabId === undefined) return;
  const info = await sendToPage<PageInfo>({ type: 'page-info' });
  // No content script: the tab was opened before the extension was installed or reloaded
  $('reload-hint').hidden = !!info || !enabled.checked;
  $('page-controls').hidden = !info?.active;
  if (!info) return;
  if (!glossaryStarted) {
    glossaryStarted = true;
    void initGlossary(info.titleKey);
  }
  $('original').setAttribute('aria-pressed', String(info.showingOriginal));

  const status: TabStatus = await chrome.runtime.sendMessage({ type: 'tab-status', tabId });
  $('stat-done').textContent = String(status.done ?? 0);
  $('stat-pending').textContent = String(status.pending);
  $('stat-errors').textContent = String(status.errors);
  $('stat-errors-wrap').hidden = status.errors === 0;
  $('stat-waiting').hidden = !status.waiting;
  $('retry-errors').hidden = status.errors === 0;
  const problem = status.errors > 0 && status.lastError ? explain(status.lastError, 'page') : null;
  showProblem('tab', problem && problem.title !== healthProblem ? problem : null);
}

async function sendToPage<T = void>(message: PopupToPage): Promise<T | undefined> {
  if (tabId === undefined) return undefined;
  try {
    return await chrome.tabs.sendMessage(tabId, message);
  } catch {
    return undefined;
  }
}

// --- Errors in plain words ---

interface Problem {
  title: string;
  hint: string;
  raw: string;
}

/** Turns a raw error (a Python exception, an HTTP status) into what happened and what to do. */
function explain(raw: string, where: 'server' | 'llm' | 'page'): Problem {
  const text = raw.replace(/\s*\(повтор через \d+ с\)$/, '');
  const is = (re: RegExp) => re.test(text);
  let title: string;
  let hint: string;
  if (where === 'server' || is(/Сервер Oblachko не отвечает|Failed to fetch/)) {
    title = 'Сервер Oblachko не запущен';
    hint = 'Запустите start.bat и не закрывайте его окно. Если окно открыто, нажмите в нём Enter.';
  } else if (is(/no loaded models|нет загруженных/i)) {
    title = 'В LM Studio не загружена модель';
    hint = 'LM Studio → Developer: загрузите модель (Load Model).';
  } else if (is(/10061|refused|ConnectError|All connection attempts failed|connect/i) && (where === 'llm' || is(/LLM/))) {
    title = 'LM Studio не отвечает';
    hint = 'Откройте LM Studio → Developer и нажмите Start Server. Порт должен совпадать с llm_base_url в server\\config.toml.';
  } else if (is(/timed? ?out|timeout/i)) {
    title = 'Модель отвечает слишком долго';
    hint = 'Видеокарта занята или модель не влезает в память. Попробуйте модель поменьше или контекст 4096.';
  } else if (where === 'llm' || is(/LLM/)) {
    title = 'Ошибка модели';
    hint = 'Проверьте LM Studio: сервер запущен, модель загружена.';
  } else if (is(/скачать картинку|CDN|не картинк/)) {
    title = 'Сайт не отдал картинку';
    hint = 'Прокрутите страницу так, чтобы она была видна целиком: Oblachko снимет её со скриншота.';
  } else if (is(/Extension context invalidated|Receiving end/)) {
    title = 'Расширение перезагрузилось';
    hint = 'Обновите вкладку (F5).';
  } else if (is(/^Сервер: 5\d\d/)) {
    title = 'Сервер не смог перевести страницу';
    hint = 'Подробности в окне start.bat. Попробуйте повторить.';
  } else {
    title = 'Не получилось перевести';
    hint = 'Попробуйте повторить.';
  }
  return { title, hint, raw: text };
}

function showProblem(prefix: 'health' | 'tab', problem: Problem | null): void {
  $(`${prefix}-problem`).hidden = !problem;
  if (!problem) return;
  $(`${prefix}-title`).textContent = problem.title;
  $(`${prefix}-hint`).textContent = problem.hint;
  $(`${prefix}-raw`).textContent = problem.raw;
}

// --- Name glossary of the title open in the tab ---

let glossaryTitle = '';

async function initGlossary(title: string): Promise<void> {
  glossaryTitle = title;
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
    await sendToPage({ type: 'retranslate' });
    glossaryStatus.textContent = 'Сохранено. Страница переводится заново с новыми именами.';
  } catch {
    glossaryStatus.textContent = 'Не удалось сохранить: сервер недоступен.';
  }
}

void init();
