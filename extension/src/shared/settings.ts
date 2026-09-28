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
