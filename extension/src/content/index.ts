import type { PageInfo, PageInfoRequest } from '../shared/messages';
import { siteKey, siteSettings, type Lang } from '../shared/settings';
import { PageTranslator } from './page-translator';
import { titleKey } from './title';

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

// The popup asks which title is open to show its name glossary
chrome.runtime.onMessage.addListener((msg: PageInfoRequest, _sender, sendResponse: (info: PageInfo) => void) => {
  if (msg.type === 'page-info') sendResponse({ titleKey: titleKey() });
  return false;
});

void sync();
