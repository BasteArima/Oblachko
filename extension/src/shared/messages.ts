import type { Lang } from './settings';

/** One translated text block, coordinates in pixels of the original image. */
export interface Block {
  id: number;
  /** x, y, w, h of the source text: covered with the background colour */
  text_bbox: [number, number, number, number];
  /** x, y, w, h of the area to write the translation in (the inside of the bubble) */
  bbox: [number, number, number, number];
  lang: 'ja' | 'en';
  vertical: boolean;
  /** Sound effect outside bubbles: drawn as a caption over the art, without a cover */
  sfx: boolean;
  bg: string;
  fg: string;
  src: string;
  dst: string;
}

export interface PageResult {
  width: number;
  height: number;
  lang: 'ja' | 'en';
  model: string;
  cached: boolean;
  timings: Record<string, number>;
  blocks: Block[];
}

export type ImagePayload =
  | { kind: 'url'; url: string }
  | { kind: 'data'; base64: string; mime: string };

export interface TranslateRequest {
  type: 'translate';
  image: ImagePayload;
  lang: Lang;
  /** Chapter: pages share translation context */
  contextKey: string;
  /** Title: chapters share the name glossary */
  titleKey: string;
  /** 0 = on screen, 1 = near the viewport, 2 = hidden preloaded page */
  priority: number;
  /** Sent as Referer when downloading a url image: many CDNs refuse hotlinks without it */
  pageUrl: string;
}

export interface HealthRequest {
  type: 'health';
}

/** Screenshot of the visible part of the sender's tab. */
export interface CaptureRequest {
  type: 'capture';
}

export type CaptureResponse = { ok: true; dataUrl: string } | { ok: false; error: string };

/** Content script -> service worker: progress on this tab (toolbar badge, popup). */
export interface StatusMessage {
  type: 'status';
  pending: number;
  errors: number;
  lastError?: string;
}

/** Popup -> service worker: the last status of a tab. */
export interface TabStatusRequest {
  type: 'tab-status';
  tabId: number;
}

export type TabStatus = Omit<StatusMessage, 'type'>;

/** Popup -> content script of the active tab. */
export type PopupToPage = { type: 'page-info' } | { type: 'retranslate' };

export interface PageInfo {
  titleKey: string;
}

export type Message = TranslateRequest | HealthRequest | CaptureRequest | StatusMessage | TabStatusRequest;

export interface GlossaryEntry {
  src: string;
  dst: string;
  manual?: boolean;
}

export type TranslateResponse =
  | { ok: true; result: PageResult }
  /**
   * code 'fetch': the image could not be downloaded, the page should fall back to a screenshot;
   * code 'skip': the server says it isn't a raster image (SVG logo, HTML error page): ignore quietly
   */
  | { ok: false; error: string; code?: 'fetch' | 'skip' };

export interface HealthResponse {
  ok: boolean;
  error?: string;
  version?: string;
  device?: string;
  queue?: number;
  llm?: { url: string; ok: boolean; model: string | null; name?: string; error?: string };
}
