/**
 * Draws translations over page images without touching the page's own DOM layout.
 *
 * One fixed, click-through layer in a closed shadow root sits above the page. Every translated
 * image gets a box that follows the image's on-screen rect; inside it a "stage" laid out in the
 * image's natural pixels is CSS-scaled to the rendered size. Text is fitted once in natural
 * pixels, so zoom, resize and scrolling never need a re-fit.
 */
import type { PageResult } from '../shared/messages';
import { contentRect, type PageElement } from './geometry';

const STYLE = `
.layer { position: fixed; inset: 0; pointer-events: none; }
.page { position: absolute; left: 0; top: 0; overflow: hidden; }
.stage { position: absolute; left: 0; top: 0; transform-origin: 0 0; }
.layer.peek .stage { display: none; }
.cover { position: absolute; border-radius: 6px; }
.text {
  position: absolute;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2px 4px;
  transform: translate(-50%, -50%);
  text-align: center;
  /* No plate: the bubble area is larger than the cleaned text box and a rectangle would cover
     the bubble outline. A halo in the bubble colour keeps letters readable over leftover lines. */
  text-shadow: 0 0 2px var(--bg), 0 0 2px var(--bg), 0 0 3px var(--bg), 0 0 5px var(--bg);
  font-family: 'Comic Sans MS', 'Segoe Print', 'Trebuchet MS', sans-serif;
  font-weight: 700;
  line-height: 1.1;
  white-space: pre-line;
  overflow-wrap: break-word;
  hyphens: auto;
}
.badge {
  position: absolute;
  top: 6px;
  right: 6px;
  padding: 2px 8px;
  border-radius: 10px;
  font: 600 12px/18px system-ui, sans-serif;
  color: #fff;
  background: rgba(91, 110, 225, 0.9);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
}
.badge.error { background: rgba(217, 48, 37, 0.92); pointer-events: auto; cursor: help; }
.badge.pending::after { content: '…'; animation: blink 1s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0.3; } }
`;

/** Font size limits as a fraction of the page height (≈18–50 px on a 1600 px page). */
const MIN_FONT = 0.011;
const MAX_FONT = 0.031;
/** Font size cap from the box width: room for about this many average Cyrillic letters per line. */
const CHARS_PER_LINE = 4.5;
/** Height / width of a typical manga page. */
const PAGE_ASPECT = 1.45;

export class Overlay {
  private readonly host: HTMLElement;
  private readonly layer: HTMLElement;
  private readonly views = new Set<PageView>();
  private readonly resizeObserver = new ResizeObserver(() => this.schedule());
  private readonly timer: number;
  private raf = 0;

  constructor() {
    this.host = document.createElement('oblachko-overlay');
    this.host.style.cssText = 'all: initial; position: fixed; inset: 0; pointer-events: none; z-index: 2147483646;';
    const root = this.host.attachShadow({ mode: 'closed' });
    const style = document.createElement('style');
    style.textContent = STYLE;
    this.layer = document.createElement('div');
    this.layer.className = 'layer';
    root.append(style, this.layer);
    document.documentElement.append(this.host);

    addEventListener('scroll', this.schedule, { capture: true, passive: true });
    addEventListener('resize', this.schedule, { passive: true });
    addEventListener('keydown', this.onKey, true);
    addEventListener('keyup', this.onKey, true);
    addEventListener('blur', this.onBlur);
    // Readers flip pages by toggling display/classes without any scroll or resize event
    this.timer = window.setInterval(this.schedule, 500);
  }

  attach(el: PageElement): PageView {
    const view = new PageView(el, this.layer, () => {
      this.views.delete(view);
      this.resizeObserver.unobserve(el);
    });
    this.views.add(view);
    this.resizeObserver.observe(el);
    this.schedule();
    return view;
  }

  /** Hide everything for a moment, e.g. while the tab is being screenshotted. */
  setHidden = (hidden: boolean): void => {
    this.host.style.visibility = hidden ? 'hidden' : '';
  };

  destroy(): void {
    removeEventListener('scroll', this.schedule, { capture: true });
    removeEventListener('resize', this.schedule);
    removeEventListener('keydown', this.onKey, true);
    removeEventListener('keyup', this.onKey, true);
    removeEventListener('blur', this.onBlur);
    clearInterval(this.timer);
    cancelAnimationFrame(this.raf);
    this.resizeObserver.disconnect();
    this.host.remove();
  }

  schedule = (): void => {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => {
      this.raf = 0;
      for (const view of this.views) view.update();
    });
  };

  /** Hold Alt to peek at the original. */
  private onKey = (e: KeyboardEvent): void => {
    if (e.key !== 'Alt') return;
    this.layer.classList.toggle('peek', e.type === 'keydown');
    e.preventDefault(); // otherwise Chrome focuses its menu on Alt release
  };

  private onBlur = (): void => this.layer.classList.remove('peek');
}

export class PageView {
  private readonly el = document.createElement('div');
  private readonly stage = document.createElement('div');
  private readonly badge = document.createElement('div');
  private result: PageResult | null = null;
  private needsFit = false;

  constructor(
    private readonly source: PageElement,
    layer: HTMLElement,
    private readonly onRemove: () => void,
  ) {
    this.el.className = 'page';
    this.stage.className = 'stage';
    this.el.append(this.stage, this.badge);
    layer.append(this.el);
    this.setPending();
  }

  setPending(): void {
    this.badge.className = 'badge pending';
    this.badge.textContent = 'Перевод';
    this.badge.removeAttribute('title');
  }

  setError(message: string): void {
    this.badge.className = 'badge error';
    this.badge.textContent = '!';
    this.badge.title = `Oblachko: ${message}`;
  }

  /** The page can only be screenshotted once it's fully on screen. */
  setWaitingForView(): void {
    this.badge.className = 'badge';
    this.badge.textContent = 'Покажите страницу целиком';
    this.badge.removeAttribute('title');
  }

  render(result: PageResult): void {
    this.result = result;
    this.badge.hidden = true;
    this.stage.replaceChildren();
    this.stage.style.width = `${result.width}px`;
    this.stage.style.height = `${result.height}px`;

    for (const block of result.blocks) {
      const [tx, ty, tw, th] = block.text_bbox;
      const cover = document.createElement('div');
      cover.className = 'cover';
      Object.assign(cover.style, { left: `${tx - 2}px`, top: `${ty - 2}px`, width: `${tw + 4}px`, height: `${th + 4}px`, background: block.bg });

      const [x, y, w, h] = block.bbox;
      const text = document.createElement('div');
      text.className = 'text';
      text.lang = 'ru';
      text.textContent = block.dst; // LLM output: never innerHTML
      Object.assign(text.style, {
        left: `${x + w / 2}px`,
        top: `${y + h / 2}px`,
        width: `${w}px`,
        minHeight: `${h}px`,
        color: block.fg,
      });
      text.style.setProperty('--bg', block.bg);
      text.dataset.w = String(w);
      text.dataset.h = String(h);
      this.stage.append(cover, text);
    }
    this.needsFit = true;
    this.update();
  }

  remove(): void {
    this.el.remove();
    this.onRemove();
  }

  update(): void {
    if (!this.source.isConnected) {
      this.remove();
      return;
    }
    const rect = contentRect(this.source);
    const visible =
      rect.width > 1 && rect.height > 1 && rect.bottom > 0 && rect.top < innerHeight && rect.right > 0 && rect.left < innerWidth;
    this.el.style.display = visible ? '' : 'none';
    if (!visible) return;

    this.el.style.transform = `translate(${rect.left}px, ${rect.top}px)`;
    this.el.style.width = `${rect.width}px`;
    this.el.style.height = `${rect.height}px`;
    if (this.result) {
      this.stage.style.transform = `scale(${rect.width / this.result.width}, ${rect.height / this.result.height})`;
      if (this.needsFit) {
        // Needs layout, so only once the box is displayed
        this.needsFit = false;
        this.fitAll();
      }
    }
  }

  private fitAll(): void {
    // Font limits scale with a normal page's height; a webtoon strip is many pages tall
    const pageH = Math.min(this.result!.height, this.result!.width * PAGE_ASPECT);
    for (const el of this.stage.querySelectorAll<HTMLElement>('.text')) {
      // Narrow tall bubbles (vertical Japanese) would otherwise take one huge word per line
      const maxByWidth = Number(el.dataset.w) / CHARS_PER_LINE;
      fitText(el, Number(el.dataset.h), Math.round(pageH * MIN_FONT), Math.round(Math.min(pageH * MAX_FONT, maxByWidth)));
    }
  }
}

/** Largest font size (natural px) at which the text fits the bubble box; boxes grow past it only at the minimum size. */
function fitText(el: HTMLElement, boxH: number, minSize: number, maxSize: number): void {
  let lo = minSize;
  let hi = Math.max(minSize, maxSize);
  let best = minSize;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    el.style.fontSize = `${mid}px`;
    if (el.scrollHeight <= boxH + 1 && el.scrollWidth <= el.clientWidth + 1) {
      best = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  el.style.fontSize = `${best}px`;
}
