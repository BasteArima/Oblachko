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
  contextKey: string;
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

export interface StatusMessage {
  type: 'status';
  pending: number;
  errors: number;
}

export type Message = TranslateRequest | HealthRequest | CaptureRequest | StatusMessage;

export type TranslateResponse =
  | { ok: true; result: PageResult }
  /** code 'fetch': the image could not be downloaded, the page should fall back to a screenshot */
  | { ok: false; error: string; code?: 'fetch' };

export interface HealthResponse {
  ok: boolean;
  error?: string;
  device?: string;
  queue?: number;
  llm?: { url: string; ok: boolean; model: string | null; error?: string };
}
