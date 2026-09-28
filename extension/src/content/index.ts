import { siteKey, siteSettings, type Lang } from '../shared/settings';
import { PageTranslator } from './page-translator';

const host = siteKey(location.hostname);
let active: { translator: PageTranslator; lang: Lang } | null = null;

async function sync(): Promise<void> {
  const site = await siteSettings(host);
  if (active && (!site.enabled || active.lang !== site.lang)) {
    active.translator.destroy();
    active = null;
  }
  if (site.enabled && !active) {
    active = { translator: new PageTranslator(site.lang), lang: site.lang };
  }
}

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'sync' && changes.sites) void sync();
});
void sync();
