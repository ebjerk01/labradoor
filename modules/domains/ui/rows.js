// The joined hostname rows, recomputed only when one of the source modules has fresh data (ctx.peer is read-only).
import { join } from './join.js';

let memo = { key: [], rows: [] };

export function rows(ctx) {
  const src = { npm: ctx.peer('npm'), cloudflare: ctx.peer('cloudflare'), drift: ctx.peer('drift'), unifi: ctx.peer('unifi') };
  const key = [src.npm, src.cloudflare, src.drift, src.unifi];
  if (!src.npm && !src.cloudflare) return [];
  if (key.every((k, i) => k === memo.key[i])) return memo.rows;
  memo = { key, rows: join(src) };
  return memo.rows;
}
