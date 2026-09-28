/**
 * Finds manga pages on the current site and gets them translated, closest to the reader first:
 *   0 - on screen, 1 - within ~1.5 screens (prefetch), 2 - preloaded but hidden (paged readers).
 */
import type { ImagePayload, PageResult, StatusMessage, TranslateRequest, TranslateResponse } from '../shared/messages';
import type { Lang } from '../shared/settings';
import { fullyVisible, naturalSize, type PageElement } from './geometry';
import { capturePixels, contentKey, NotVisibleError, readPixels } from './image-source';
import { Overlay, type PageView } from './overlay';
import { chapterKey, titleKey } from './title';

/** Smaller images are avatars, thumbnails and ads, not pages. */
const MIN_SIDE = 300;
const PREFETCH_SCREENS = 1.5;
const RESCAN_MS = 1000;
/** Key of a tainted canvas: its content can't be read, so it's translated once. */
const OPAQUE_CANVAS = 'canvas:opaque';

interface PageState {
  key: string;
  /** 'capture': pixels unreadable, waiting until the page is fully on screen to screenshot it */
  status: 'pending' | 'capture' | 'done' | 'error';
  priority: number;
  view: PageView;
  capturing?: boolean;
}

export class PageTranslator {
  private readonly overlay = new Overlay();
  private readonly pages = new Map<PageElement, PageState>();
  private readonly watched = new WeakSet<PageElement>();
  /** Canvases mid-redraw: a new picture is translated only after it stayed the same for one rescan. */
  private readonly canvasKeys = new WeakMap<HTMLCanvasElement, string>();
  private readonly intersection = new IntersectionObserver((entries) => entries.forEach((e) => this.check(e.target as PageElement)), {
    rootMargin: `${PREFETCH_SCREENS * 100}% 0px`,
  });
  private readonly mutations = new MutationObserver((records) => this.onMutations(records));
  private readonly timer: number;

  constructor(private readonly lang: Lang) {
    this.mutations.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['src', 'srcset'] });
    this.all().forEach((el) => this.watch(el));
    // Paged readers preload hidden pages and flip them by toggling visibility, canvas readers
    // redraw in place: neither produces anything to observe
    this.timer = window.setInterval(() => this.all().forEach((el) => this.check(el)), RESCAN_MS);
  }

  destroy(): void {
    clearInterval(this.timer);
    this.intersection.disconnect();
    this.mutations.disconnect();
    this.overlay.destroy();
    this.pages.clear();
    this.reportStatus();
  }

  private all(): NodeListOf<PageElement> {
    return document.querySelectorAll<PageElement>('img, canvas');
  }

  private onMutations(records: MutationRecord[]): void {
    for (const record of records) {
      if (record.type === 'attributes') {
        if (record.target instanceof HTMLImageElement) this.check(record.target);
        continue;
      }
      for (const node of record.addedNodes) {
        if (node instanceof HTMLImageElement || node instanceof HTMLCanvasElement) this.watch(node);
        else if (node instanceof Element) node.querySelectorAll<PageElement>('img, canvas').forEach((el) => this.watch(el));
      }
    }
  }

  private watch(el: PageElement): void {
    if (this.watched.has(el)) return;
    this.watched.add(el);
    this.intersection.observe(el);
    if (el instanceof HTMLImageElement) el.addEventListener('load', () => this.check(el));
    this.check(el);
  }

  private check(el: PageElement): void {
    if (!isPage(el)) return;
    const key = this.stableKey(el);
    if (key === null) return;

    let state = this.pages.get(el);
    if (state && state.key !== key) {
      // Same element now shows another page
      state.view.remove();
      this.pages.delete(el);
      state = undefined;
    }

    const priority = priorityOf(el);
    if (priority === null) return;
    if (!state) {
      this.request(el, key, priority);
    } else if (state.status === 'capture') {
      void this.capture(el, state);
    } else if (state.status === 'pending' && priority < state.priority) {
      // Scrolled into view while waiting in the prefetch queue: the server bumps the queued job
      state.priority = priority;
      void this.send(el, state, priority);
    }
  }

  /** What the element shows; null while a canvas is still being redrawn. */
  private stableKey(el: PageElement): string | null {
    const key = contentKey(el);
    if (!(el instanceof HTMLCanvasElement)) return key;
    if (key === null) return OPAQUE_CANVAS;
    const previous = this.canvasKeys.get(el);
    this.canvasKeys.set(el, key);
    const current = this.pages.get(el)?.key;
    return key === previous || key === current ? key : null;
  }

  private request(el: PageElement, key: string, priority: number): void {
    const state: PageState = { key, status: 'pending', priority, view: this.overlay.attach(el) };
    this.pages.set(el, state);
    this.reportStatus();
    void this.send(el, state, priority);
  }

  private async send(el: PageElement, state: PageState, priority: number): Promise<void> {
    let payload: ImagePayload | null;
    try {
      payload = await readPixels(el);
    } catch (err) {
      return this.finish(el, state, failure(err));
    }
    if (payload === null) return this.needCapture(el, state);

    const response = await this.translate(payload, priority);
    if (!response.ok && response.code === 'fetch') return this.needCapture(el, state);
    this.finish(el, state, response);
  }

  private needCapture(el: PageElement, state: PageState): void {
    if (this.pages.get(el) !== state || state.status !== 'pending') return;
    state.status = 'capture';
    this.reportStatus();
    void this.capture(el, state);
  }

  private async capture(el: PageElement, state: PageState): Promise<void> {
    if (state.capturing) return;
    if (!fullyVisible(el)) {
      state.view.setWaitingForView();
      return;
    }
    state.capturing = true;
    state.view.setPending();
    let response: TranslateResponse;
    try {
      const payload = await capturePixels(el, this.overlay.setHidden);
      // On screen already and nothing to bump: keeps check() from re-reading the unreadable pixels
      state.priority = 0;
      response = await this.translate(payload, 0);
    } catch (err) {
      if (err instanceof NotVisibleError) {
        state.view.setWaitingForView();
        return;
      }
      response = failure(err);
    } finally {
      state.capturing = false;
    }
    state.status = 'pending';
    this.finish(el, state, response);
  }

  private async translate(image: ImagePayload, priority: number): Promise<TranslateResponse> {
    const request: TranslateRequest = {
      type: 'translate',
      image,
      lang: this.lang,
      contextKey: chapterKey(),
      titleKey: titleKey(),
      priority,
      pageUrl: location.href,
    };
    try {
      return await chrome.runtime.sendMessage(request);
    } catch (err) {
      return failure(err); // extension reloaded or updated under the page
    }
  }

  private finish(el: PageElement, state: PageState, response: TranslateResponse): void {
    // Page changed or already answered by an earlier (lower priority) request
    if (this.pages.get(el) !== state || state.status !== 'pending') return;
    if (response.ok) {
      state.status = 'done';
      state.view.render(response.result);
      logResult(response.result);
    } else {
      state.status = 'error';
      state.view.setError(response.error);
      console.warn('[Oblachko]', response.error);
    }
    this.reportStatus(response.ok ? undefined : response.error);
  }

  private reportStatus(lastError?: string): void {
    let pending = 0;
    let errors = 0;
    for (const state of this.pages.values()) {
      if (state.status === 'pending') pending++;
      else if (state.status === 'error') errors++;
    }
    const status: StatusMessage = { type: 'status', pending, errors, lastError };
    chrome.runtime.sendMessage(status).catch(() => {});
  }
}

function isPage(el: PageElement): boolean {
  if (el instanceof HTMLImageElement && !el.complete) return false;
  const [w, h] = naturalSize(el);
  if (w < MIN_SIDE || h < MIN_SIDE) return false;
  // Canvases are also used for effects and charts; a reader's canvas is big on screen
  if (el instanceof HTMLCanvasElement) {
    const rect = el.getBoundingClientRect();
    return rect.width >= MIN_SIDE / 2 && rect.height >= MIN_SIDE / 2;
  }
  return true;
}

function priorityOf(el: PageElement): number | null {
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return el.isConnected ? 2 : null;
  const onScreen = rect.bottom > 0 && rect.top < innerHeight && rect.right > 0 && rect.left < innerWidth;
  if (onScreen) return 0;
  const margin = innerHeight * PREFETCH_SCREENS;
  return rect.bottom > -margin && rect.top < innerHeight + margin ? 1 : null;
}

function failure(err: unknown): TranslateResponse {
  return { ok: false, error: err instanceof Error ? err.message : String(err) };
}

function logResult(result: PageResult): void {
  const t = result.timings;
  const where = result.cached ? 'cache' : `detect ${t.detect}s, ocr ${t.ocr}s, llm ${t.translate}s`;
  console.debug(`[Oblachko] ${result.blocks.length} blocks (${where})`);
}
