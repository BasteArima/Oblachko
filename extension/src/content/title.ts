/**
 * Chapter and title identity from the page URL, for the server's translation context (chapter)
 * and name glossary (title).
 */

/** Path segments that are followed by the title's slug or id: /title/<id>, /manga-raw/<slug>, ... */
const TITLE_SEGMENT = /^(title|manga|manhwa|manhua|series|comic|comics|webtoon|work|manga-raw)$/i;

/** Pages of one chapter share context. Paged readers put the page number last (MangaDex: /chapter/<id>/2). */
export function chapterKey(): string {
  return location.origin + location.pathname.replace(/\/\d+\/?$/, '');
}

/**
 * The title this chapter belongs to:
 * 1. from the URL itself (comix.to/title/<slug>/<chapter>, klmanga.zone/manga-raw/<slug>/chapter-64)
 * 2. from same-site links to a title page (MangaDex chapter URLs are /chapter/<id>, the reader links
 *    /title/<id>). Menus also link things like /title/random, so the title linked most often wins,
 *    and a link whose text is in the tab title counts extra.
 * 3. the site plus the page title with numbers stripped
 */
export function titleKey(): string {
  const fromUrl = titlePath(location.pathname);
  if (fromUrl) return location.origin + fromUrl;

  const docTitle = document.title.toLowerCase();
  const scores = new Map<string, number>();
  for (const link of document.querySelectorAll<HTMLAnchorElement>('a[href]')) {
    if (link.origin !== location.origin) continue;
    const path = titlePath(link.pathname);
    if (!path) continue;
    const text = link.textContent?.trim().toLowerCase() ?? '';
    const bonus = text.length > 3 && docTitle.includes(text) ? 5 : 0;
    scores.set(path, (scores.get(path) ?? 0) + 1 + bonus);
  }
  const best = [...scores].sort((a, b) => b[1] - a[1])[0];
  if (best) return location.origin + best[0];

  return `${location.origin}|${document.title.replace(/\d+/g, '').replace(/\s+/g, ' ').trim()}`;
}

function titlePath(pathname: string): string | null {
  const parts = pathname.split('/').filter(Boolean);
  const i = parts.findIndex((p) => TITLE_SEGMENT.test(p));
  return i >= 0 && parts[i + 1] ? `/${parts.slice(0, i + 2).join('/')}` : null;
}
