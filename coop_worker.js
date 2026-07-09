// coop_worker.js — Cloudflare Worker для синхронизации вкладки Collab в
// SI-HYX. Хранит текстовый обзор пака по коду комнаты в KV и
// отдаёт объединённое состояние всех соавторов.
//
// ── Протокол ──────────────────────────────────────────────────────────────
//   POST /coop/<room>   тело: {author, outline, updated}
//                       → сохраняет/обновляет обзор автора в комнате.
//   GET  /coop/<room>   → {authors: {<author>: {outline, updated}}}
//
// Комната — это просто ключ KV `room:<room>`, значение — JSON вида
//   {authors: {"Голден": {outline, updated}, "Напарник": {outline, updated}}}
// с TTL 14 дней (продлевается при каждой записи), чтобы старые комнаты сами
// вычищались.
//
// ── Как развернуть ──────────────────────────────────────────────────────────
//   ПРОСТОЙ способ (мышкой, без командной строки) — см. DEPLOY_COOP.md.
//
// ── Деплой через wrangler (для тех, кто любит консоль) ───────────────────────
//   1. npm i -g wrangler   (или npx wrangler ...)
//   2. Создать KV:         wrangler kv namespace create COOP_KV
//      → вписать выданный id в wrangler.toml (см. образец ниже).
//   3. wrangler deploy
//   4. Полученный адрес вида https://<worker>.workers.dev вписать в поле
//      «Сервер» вкладки Collab (или в config.py → COOP_SYNC_URL).
//
// ── Образец wrangler.toml ───────────────────────────────────────────────────
//   name = "si-hyx-coop"
//   main = "coop_worker.js"
//   compatibility_date = "2024-11-01"
//   [[kv_namespaces]]
//   binding = "COOP_KV"
//   id = "<сюда id из шага 2>"

const TTL_SECONDS = 14 * 24 * 60 * 60;   // 14 дней
const MAX_BODY = 2 * 1024 * 1024;        // 2 МБ на один обзор — с запасом

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS });
    }

    const url = new URL(request.url);
    const m = url.pathname.match(/^\/coop\/([^/]+)\/?$/);
    if (!m) {
      return json({ error: "not found" }, 404);
    }
    const room = decodeURIComponent(m[1]).slice(0, 200);
    const key = `room:${room}`;

    if (request.method === "GET") {
      const raw = await env.COOP_KV.get(key);
      const data = raw ? JSON.parse(raw) : { authors: {} };
      return json(data);
    }

    if (request.method === "POST") {
      const text = await request.text();
      if (text.length > MAX_BODY) {
        return json({ error: "too large" }, 413);
      }
      let body;
      try {
        body = JSON.parse(text);
      } catch {
        return json({ error: "bad json" }, 400);
      }
      const author = String(body.author || "").slice(0, 80).trim();
      if (!author) {
        return json({ error: "author required" }, 400);
      }

      const raw = await env.COOP_KV.get(key);
      const data = raw ? JSON.parse(raw) : { authors: {} };
      if (!data.authors) data.authors = {};
      data.authors[author] = {
        outline: body.outline || {},
        updated: Number(body.updated) || Math.floor(Date.now() / 1000),
      };
      await env.COOP_KV.put(key, JSON.stringify(data), {
        expirationTtl: TTL_SECONDS,
      });
      return json({ ok: true, authors: Object.keys(data.authors).length });
    }

    return json({ error: "method not allowed" }, 405);
  },
};
