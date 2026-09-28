import type { HealthResponse } from '../shared/messages';
import { loadSettings, siteKey, siteSettings, updateServerUrl, updateSite, type Lang } from '../shared/settings';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

const statusEl = $<HTMLParagraphElement>('status');
const dot = $<HTMLSpanElement>('status-dot');
const enabled = $<HTMLInputElement>('enabled');
const lang = $<HTMLSelectElement>('lang');
const serverUrl = $<HTMLInputElement>('server-url');

async function init(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const url = tab?.url ? new URL(tab.url) : null;
  const host = url && /^https?:$/.test(url.protocol) ? siteKey(url.hostname) : null;

  if (host) {
    $('host').textContent = host;
    const site = await siteSettings(host);
    enabled.checked = site.enabled;
    lang.value = site.lang;
    enabled.addEventListener('change', () => updateSite(host, { enabled: enabled.checked }));
    lang.addEventListener('change', () => updateSite(host, { lang: lang.value as Lang }));
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

void init();
