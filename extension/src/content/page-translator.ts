/**
 * Finds manga pages on the current site and gets them translated, closest to the reader first:
 *   0 - on screen, 1 - within ~1.5 screens (prefetch), 2 - preloaded but hidden (paged readers).
 */
import type { PageResult, TranslateRequest, TranslateResponse } from '../shared/messages';
import type { Lang } from '../shared/settings';
import { imagePayload } from './image-source';
import { Overlay, type PageView } from './overlay';

/** Smaller images are avatars, thumbnails and ads, not pages. */
const MIN_SIDE = 300;
const PREFETCH_SCREENS = 1.5;
const RESCAN_MS = 1000;

interface PageState {
  src: string;
  status: 'pending' | 'done' | 'error';
  priority: number;
  view: PageView;
}

export class PageTranslator {
  private readonly overlay = new Overlay();
  private readonly pages = new Map<HTMLImageElement, PageState>();
  private readonly watched = new WeakSet<HTMLImageElement>();
  private readonly intersection = new IntersectionObserver((entries) => entries.forEach((e) => this.check(e.target as HTMLImageElement)), {
    rootMargin: `${PREFETCH_SCREENS * 100}% 0px`,
  });
  private readonly mutations = new MutationObserver((records) => this.onMutations(records));
  private readonly timer: number;

  constructor(private readonly lang: Lang) {
    this.mutations.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['src', 'srcset'] });
    document.querySelectorAll('img').forEach((img) => this.watch(img));
    // Paged readers preload hidden pages and flip them by toggling visibility: nothing to observe
    this.timer = window.setInterval(() => document.querySelectorAll('img').forEach((img) => this.check(img)), RESCAN_MS);
  }

  destroy(): void {
    clearInterval(this.timer);
    this.intersection.disconnect();
    this.mutations.disconnect();
    this.overlay.destroy();
    this.pages.clear();
    this.reportStatus();
  }

  private onMutations(records: MutationRecord[]): void {
    for (const record of records) {
      if (record.type === 'attributes') {
        if (record.target instanceof HTMLImageElement) this.check(record.target);
        continue;
      }
      for (const node of record.addedNodes) {
        if (node instanceof HTMLImageElement) this.watch(node);
        else if (node instanceof Element) node.querySelectorAll('img').forEach((img) => this.watch(img));
      }
    }
  }

  private watch(img: HTMLImageElement): void {
    if (this.watched.has(img)) return;
    this.watched.add(img);
    this.intersection.observe(img);
    img.addEventListener('load', () => this.check(img));
    this.check(img);
  }

  private check(img: HTMLImageElement): void {
    if (!img.complete || img.naturalWidth < MIN_SIDE || img.naturalHeight < MIN_SIDE) return;
    const src = img.currentSrc || img.src;
    if (!src) return;

    let state = this.pages.get(img);
    if (state && state.src !== src) {
      // Same <img> reused for another page
      state.view.remove();
      this.pages.delete(img);
      state = undefined;
    }

    const priority = priorityOf(img);
    if (priority === null) return;
    if (!state) {
      this.request(img, src, priority);
    } else if (state.status === 'pending' && priority < state.priority) {
      // Scrolled into view while waiting in the prefetch queue: the server bumps the queued job
      state.priority = priority;
      void this.send(img, state, priority);
    }
  }

  private request(img: HTMLImageElement, src: string, priority: number): void {
    const state: PageState = { src, status: 'pending', priority, view: this.overlay.attach(img) };
    this.pages.set(img, state);
    this.reportStatus();
    void this.send(img, state, priority);
  }

  private async send(img: HTMLImageElement, state: PageState, priority: number): Promise<void> {
    let response: TranslateResponse;
    try {
      const request: TranslateRequest = {
        type: 'translate',
        image: await imagePayload(state.src),
        lang: this.lang,
        contextKey: chapterKey(),
        priority,
      };
      response = await chrome.runtime.sendMessage(request);
    } catch (err) {
      response = { ok: false, error: err instanceof Error ? err.message : String(err) };
    }
    // Page changed or already answered by an earlier (lower priority) request
    if (this.pages.get(img) !== state || state.status !== 'pending') return;

    if (response.ok) {
      state.status = 'done';
      state.view.render(response.result);
      logResult(response.result);
    } else {
      state.status = 'error';
      state.view.setError(response.error);
      console.warn('[Oblachko]', response.error);
    }
    this.reportStatus();
  }

  private reportStatus(): void {
    let pending = 0;
    let errors = 0;
    for (const state of this.pages.values()) {
      if (state.status === 'pending') pending++;
      else if (state.status === 'error') errors++;
    }
    chrome.runtime.sendMessage({ type: 'status', pending, errors }).catch(() => {});
  }
}

function priorityOf(img: HTMLImageElement): number | null {
  const rect = img.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return img.isConnected ? 2 : null;
  const onScreen = rect.bottom > 0 && rect.top < innerHeight && rect.right > 0 && rect.left < innerWidth;
  if (onScreen) return 0;
  const margin = innerHeight * PREFETCH_SCREENS;
  return rect.bottom > -margin && rect.top < innerHeight + margin ? 1 : null;
}

/** Pages of one chapter share translation context. Paged readers put the page number last (MangaDex: /chapter/<id>/2). */
function chapterKey(): string {
  return location.origin + location.pathname.replace(/\/\d+\/?$/, '');
}

function logResult(result: PageResult): void {
  const t = result.timings;
  const where = result.cached ? 'cache' : `detect ${t.detect}s, ocr ${t.ocr}s, llm ${t.translate}s`;
  console.debug(`[Oblachko] ${result.blocks.length} blocks (${where})`);
}
