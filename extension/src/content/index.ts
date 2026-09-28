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
  const translator = active?.translator;
  switch (msg.type) {
    // The popup asks which title is open (name glossary) and what the page shows
    case 'page-info':
      sendResponse({ titleKey: titleKey(), active: !!translator, showingOriginal: translator?.showingOriginal ?? false });
      break;
    // Redo the pages after the glossary changed, or on "Перевести заново"
    case 'retranslate':
      translator?.retranslate(msg.fresh);
      break;
    case 'retry-errors':
      translator?.retryErrors();
      break;
    case 'set-original':
      translator?.setOriginal(msg.on);
      break;
  }
  return false;
});

void sync();
