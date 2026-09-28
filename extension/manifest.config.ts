import { defineManifest } from '@crxjs/vite-plugin';
import pkg from './package.json' with { type: 'json' };

const icons = {
  16: 'icons/icon16.png',
  32: 'icons/icon32.png',
  48: 'icons/icon48.png',
  128: 'icons/icon128.png',
};

export default defineManifest({
  manifest_version: 3,
  name: 'Oblachko',
  version: pkg.version,
  description: 'Переводит мангу прямо на странице с помощью локальной нейросети',
  icons,
  action: {
    default_popup: 'src/popup/index.html',
    default_icon: icons,
  },
  background: {
    service_worker: 'src/background/index.ts',
    type: 'module',
  },
  content_scripts: [
    {
      // Injected everywhere but idle until the site is enabled in the popup
      matches: ['<all_urls>'],
      js: ['src/content/index.ts'],
      run_at: 'document_idle',
    },
  ],
  // declarativeNetRequestWithHostAccess: set Referer on image downloads (anti-hotlink CDNs)
  permissions: ['storage', 'declarativeNetRequestWithHostAccess'],
  // Page images live on arbitrary CDNs; the service worker downloads them past CORS,
  // and it also needs to reach the local server
  host_permissions: ['<all_urls>'],
});
