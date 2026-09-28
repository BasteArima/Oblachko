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
}

export interface HealthRequest {
  type: 'health';
}

export interface StatusMessage {
  type: 'status';
  pending: number;
  errors: number;
}

export type Message = TranslateRequest | HealthRequest | StatusMessage;

export type TranslateResponse = { ok: true; result: PageResult } | { ok: false; error: string };

export interface HealthResponse {
  ok: boolean;
  error?: string;
  device?: string;
  queue?: number;
  llm?: { url: string; ok: boolean; model: string | null; error?: string };
}
