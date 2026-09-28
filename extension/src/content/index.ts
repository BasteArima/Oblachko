import type { PageInfo, PopupToPage } from '../shared/messages';
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

chrome.runtime.onMessage.addListener((msg: PopupToPage, _sender, sendResponse: (info: PageInfo) => void) => {
  // The popup asks which title is open to show its name glossary
  if (msg.type === 'page-info') sendResponse({ titleKey: titleKey() });
  // ...and asks to redo the pages after the glossary changed, or to retry failed ones
  else if (msg.type === 'retranslate') active?.translator.retranslate();
  return false;
});

void sync();
