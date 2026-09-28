export type Lang = 'auto' | 'ja' | 'en';

export interface SiteSettings {
  enabled: boolean;
  lang: Lang;
}

export interface Settings {
  serverUrl: string;
  sites: Record<string, SiteSettings>;
}

export const DEFAULT_SETTINGS: Settings = {
  serverUrl: 'http://127.0.0.1:8765',
  sites: {},
};

export const DEFAULT_SITE: SiteSettings = { enabled: false, lang: 'auto' };

export function siteKey(hostname: string): string {
  return hostname.replace(/^www\./, '');
}

export async function loadSettings(): Promise<Settings> {
  const stored = await chrome.storage.sync.get({ ...DEFAULT_SETTINGS } as Record<string, unknown>);
  return { ...DEFAULT_SETTINGS, ...(stored as Partial<Settings>) };
}

export async function siteSettings(host: string): Promise<SiteSettings> {
  const { sites } = await loadSettings();
  return { ...DEFAULT_SITE, ...sites[host] };
}

export async function updateSite(host: string, patch: Partial<SiteSettings>): Promise<void> {
  const settings = await loadSettings();
  settings.sites[host] = { ...DEFAULT_SITE, ...settings.sites[host], ...patch };
  await chrome.storage.sync.set({ sites: settings.sites });
}

export async function updateServerUrl(serverUrl: string): Promise<void> {
  await chrome.storage.sync.set({ serverUrl: serverUrl.replace(/\/+$/, '') });
}

export type Backend = 'local' | 'gemini';

export interface TranslatorSettings {
  backend: Backend;
  geminiKey: string;
  geminiModel: string;
}

export const GEMINI_MODELS: { id: string; label: string }[] = [
  { id: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite: быстрый, больше бесплатных запросов' },
  { id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash: точнее, медленнее' },
];

const DEFAULT_TRANSLATOR: TranslatorSettings = { backend: 'local', geminiKey: '', geminiModel: GEMINI_MODELS[0].id };

/** In local storage, not sync: the API key stays on this computer. */
export async function loadTranslator(): Promise<TranslatorSettings> {
  const { translator } = await chrome.storage.local.get('translator');
  return { ...DEFAULT_TRANSLATOR, ...(translator as Partial<TranslatorSettings> | undefined) };
}

export async function updateTranslator(patch: Partial<TranslatorSettings>): Promise<TranslatorSettings> {
  const translator = { ...(await loadTranslator()), ...patch };
  await chrome.storage.local.set({ translator });
  return translator;
}

/** The server picks the translator per request from these headers. */
export async function translatorHeaders(): Promise<Record<string, string>> {
  const t = await loadTranslator();
  if (t.backend !== 'gemini') return { 'X-Oblachko-Backend': 'local' };
  return { 'X-Oblachko-Backend': 'gemini', 'X-Oblachko-Key': t.geminiKey.trim(), 'X-Oblachko-Model': t.geminiModel };
}
