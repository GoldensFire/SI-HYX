// tier_worker.js — Cloudflare Worker для публикации тир-листа сыгранных паков
// из вкладки «Поиск пакетов» SI-HYX. Хранит модель тир-листа в KV и отдаёт
// готовую HTML-страницу по постоянной ссылке (кликабельные ссылки на паки,
// комментарии, теги — визуально как в приложении).
//
// ── Протокол ──────────────────────────────────────────────────────────────
//   POST /tier/<id>   тело: {token, title, tiers:[...], updated}
//                     Заголовок X-Edit-Token тоже принимается вместо body.token.
//                     Первый POST на свободный <id> «занимает» его вместе с
//                     токеном; последующие требуют тот же токен (иначе 403).
//                     → {ok:true, url}
//   GET  /tier/<id>   → HTML-страница тир-листа (человеку в браузере).
//   GET  /tier/<id>?format=json → сама модель (для отладки).
//
// Ключ KV `tier:<id>` = JSON {token, model, updated}. TTL 180 дней,
// продлевается при каждой публикации — заброшенные листы сами вычищаются.
//
// ── Как развернуть ──────────────────────────────────────────────────────────
//   ПРОСТОЙ способ (мышкой, без командной строки) — см. DEPLOY_TIER.md.
//
// ── Деплой через wrangler (для консоли) ──────────────────────────────────────
//   1. npm i -g wrangler   (или npx wrangler ...)
//   2. wrangler kv namespace create TIER_KV
//      → вписать выданный id в wrangler.toml (см. образец ниже).
//   3. wrangler deploy
//   4. Полученный адрес https://<worker>.workers.dev вписать в config.py →
//      TIER_LIST_PUBLISH_URL.
//
// ── Образец wrangler.toml ───────────────────────────────────────────────────
//   name = "si-hyx-tier"
//   main = "tier_worker.js"
//   compatibility_date = "2024-11-01"
//   [[kv_namespaces]]
//   binding = "TIER_KV"
//   id = "<сюда id из шага 2>"

const TTL_SECONDS = 180 * 24 * 60 * 60;   // 180 дней, продлевается при публикации
const MAX_BODY = 1 * 1024 * 1024;         // 1 МБ на тир-лист — с запасом

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-Edit-Token",
};

const TAG_GOOD = "#a6e3a1";
const TAG_BAD = "#f38ba8";
const TAG_NEUTRAL = "#ffffff";
const TAG_KIND_ORDER = { good: 0, neutral: 1, bad: 2 };

// Те же цвета уровней сложности, что и в самом приложении (_DIFF_COLORS).
const DIFF_COLORS = {
  "лёгкий": "#a6e3a1", "средне": "#f9e2af", "сложно": "#f38ba8", "оч. сложно": "#8839ef",
};

// Заголовок сайта фиксирован — не зависит от того, что было отправлено при
// публикации (иначе старые страницы показывали бы заголовок, актуальный на
// момент ИХ публикации, а не текущий бренд, пока их не переопубликуют).
const SITE_TITLE = "Тир-лист от GoldensFire по аниме-пакам";

// Иконка вкладки — та же, что у самого приложения (icon.ico, 64×64 PNG).
const FAVICON_B64 = "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";

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

function esc(s) {
  return String(s == null ? "" : s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// Разрешаем в ссылках только http(s) — чтобы через модель нельзя было
// подсунуть javascript:/data: и т.п. в атрибут href.
function safeUrl(u) {
  const s = String(u || "").trim();
  return /^https?:\/\//i.test(s) ? s : "";
}

// Значок Steam — рисуется у названия пака, если он пришёл из Steam Workshop
// (см. renderPack). Инлайновый SVG (без внешних запросов), цвет — фирменный
// голубой Steam, тот же, что и у значка в самом приложении (fa5b.steam).
const STEAM_ICON = `<svg class="pk-steam" viewBox="0 0 24 24" width="14" height="14" ` +
  `aria-hidden="true" focusable="false"><title>Steam Workshop</title>` +
  `<circle cx="12" cy="12" r="10.5" fill="none" stroke="#66c0f4" stroke-width="1.6"/>` +
  `<circle cx="8.7" cy="15.3" r="2.1" fill="#66c0f4"/>` +
  `<circle cx="15.3" cy="8.2" r="2.4" fill="#66c0f4"/>` +
  `<line x1="8.7" y1="15.3" x2="14" y2="10" stroke="#66c0f4" stroke-width="1.3"/></svg>`;

function renderTag(tag) {
  const kind = tag && tag.kind;
  const color = kind === "bad" ? TAG_BAD : kind === "neutral" ? TAG_NEUTRAL : TAG_GOOD;
  return `<span class="tag" style="color:${color};border-color:${color}">${esc(tag && tag.text)}</span>`;
}

// Хорошие сверху, нейтральные посередине, плохие снизу; внутри группы — по
// алфавиту (по просьбе — было в порядке создания, вперемешку).
function sortTags(tags) {
  return tags.slice().sort((a, b) => {
    const ka = TAG_KIND_ORDER[(a && a.kind) || "good"] ?? 0;
    const kb = TAG_KIND_ORDER[(b && b.kind) || "good"] ?? 0;
    if (ka !== kb) return ka - kb;
    return String((a && a.text) || "").localeCompare(String((b && b.text) || ""), "ru");
  });
}

function renderPack(p) {
  const id = esc(p && p.id != null ? p.id : "");
  const name = esc(p && p.name);
  const url = safeUrl(p && p.url);
  const author = (p && p.author ? String(p.author) : "").trim();
  const authorHtml = author ? `<div class="pk-author">${esc(author)}</div>` : "";
  const difficulty = (p && p.difficulty ? String(p.difficulty) : "").trim();
  const diffColor = DIFF_COLORS[difficulty] || "#89b4fa";
  const diffHtml = difficulty
    ? `<div class="pk-diff" style="color:${diffColor}">Сложность: ${esc(difficulty)}</div>`
    : "";
  const comment = (p && p.comment ? String(p.comment) : "").trim();
  const commentHtml = comment ? `<div class="pk-comment">${esc(comment)}</div>` : "";
  const tags = sortTags(Array.isArray(p && p.tags) ? p.tags : []);
  const tagsHtml = tags.length
    ? `<div class="pk-tags">${tags.map(renderTag).join("")}</div>`
    : "";
  const steamHtml = p && p.steam ? STEAM_ICON : "";
  const inner = `<div class="pk-name">${steamHtml}${name}</div>${authorHtml}${diffHtml}${commentHtml}${tagsHtml}`;
  // Кликабельна вся карточка (не только название) — если есть ссылка на пак.
  const linkHtml = url
    ? `<a class="pack-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${inner}</a>`
    : `<div class="pack-link">${inner}</div>`;
  // Отметка «сыграно» лично для зрителя — переживает перезапуск браузера
  // (localStorage, см. renderPage/playedScript), на сервер не отправляется.
  // Вынесена ИЗ ссылки (а не внутрь <a>), чтобы клик по чекбоксу не открывал
  // страницу пака — стоп propagation в атрибуте on click.
  const playedHtml = id
    ? `<label class="pk-played" onclick="event.stopPropagation()">
         <input type="checkbox" class="played-chk" data-pid="${id}"> Сыграно
       </label>`
    : "";
  return `<div class="pack" data-pid="${id}">${linkHtml}${playedHtml}</div>`;
}

// Длинные названия уровней не влезали в узкую колонку фиксированной ширины с
// крупным шрифтом — текст дробился почти по одной букве на строку. Размер и
// ширина колонки подбираются ОДИН РАЗ под самое длинное название среди ВСЕХ
// уровней (см. renderPage) и применяются одинаково ко всем — иначе колонки
// с короткими названиями выглядели мельче/уже соседних вразнобой.
function tierLabelDims(maxLen) {
  if (maxLen <= 6) return { size: 26, width: 84 };
  if (maxLen <= 10) return { size: 20, width: 112 };
  if (maxLen <= 16) return { size: 16, width: 144 };
  return { size: 13, width: 176 };
}

function renderTier(t, dims) {
  const color = safeColor(t && t.color) || "#89b4fa";
  const name = esc(t && t.name);
  const packs = Array.isArray(t && t.packs) ? t.packs : [];
  const packsHtml = packs.length
    ? packs.map(renderPack).join("")
    : `<div class="empty">пусто</div>`;
  // clamp() вместо фиксированного px — на узких экранах колонка сама
  // сжимается пропорционально ширине вьюпорта, не только на десктопе.
  const style = `color:${color};border-color:${color};` +
    `font-size:clamp(13px, 4vw, ${dims.size}px);` +
    `flex-basis:clamp(56px, 22vw, ${dims.width}px)`;
  return `<section class="tier">
    <div class="tier-label" style="${style}">${name}</div>
    <div class="tier-packs">${packsHtml}</div>
  </section>`;
}

function safeColor(c) {
  const s = String(c || "").trim();
  return /^#[0-9a-fA-F]{3,8}$/.test(s) ? s : "";
}

function renderPage(model, updated, pageId) {
  const title = SITE_TITLE;
  const tiers = Array.isArray(model && model.tiers) ? model.tiers : [];
  const maxLen = tiers.reduce((m, t) => Math.max(m, ((t && t.name) || "").length), 0);
  const dims = tierLabelDims(maxLen);
  const tiersHtml = tiers.map((t) => renderTier(t, dims)).join("");
  const totalPacks = tiers.reduce(
    (sum, t) => sum + (Array.isArray(t && t.packs) ? t.packs.length : 0), 0);
  // Серверный рендер не знает часовой пояс зрителя — отдаём UTC как запасной
  // вариант в тексте узла и настоящий timestamp в data-ts; скрипт ниже
  // переформатирует в локальное время браузера при загрузке страницы.
  const updatedHtml = updated
    ? `<p class="sub" id="updated" data-ts="${Number(updated)}">Обновлено: ${esc(new Date(updated * 1000).toUTCString())}</p>`
    : `<p class="sub"></p>`;
  const updatedScript = updated ? `<script>
(function(){
  var el = document.getElementById('updated');
  if (!el) return;
  var ts = Number(el.getAttribute('data-ts'));
  if (!ts) return;
  var d = new Date(ts * 1000);
  var fmt = new Intl.DateTimeFormat(undefined, {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'
  });
  el.textContent = 'Обновлено: ' + fmt.format(d);
})();
</script>` : "";
  // Отметки «сыграно» — личные для зрителя, хранятся в localStorage браузера
  // (ключ привязан к id ЭТОЙ страницы, чтобы разные тир-листы на одном
  // воркере не путали друг друга) и переживают перезапуск браузера. На
  // сервер ничего не отправляется — это не совместное состояние.
  const playedScript = `<script>
(function(){
  var KEY = 'si-hyx-tier-played:${esc(pageId || "")}';
  var played = {};
  try { played = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {}
  function apply(pid, on) {
    var card = document.querySelector('.pack[data-pid="' + pid + '"]');
    if (card) card.classList.toggle('played', !!on);
  }
  Object.keys(played).forEach(function(pid){ if (played[pid]) apply(pid, true); });
  document.querySelectorAll('.played-chk').forEach(function(chk){
    var pid = chk.getAttribute('data-pid');
    chk.checked = !!played[pid];
    chk.addEventListener('change', function(){
      played[pid] = chk.checked;
      apply(pid, chk.checked);
      try { localStorage.setItem(KEY, JSON.stringify(played)); } catch (e) {}
    });
  });
})();
</script>`;
  return `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<link rel="icon" type="image/png" href="data:image/png;base64,${FAVICON_B64}">
<title>${title}</title>
<style>
  :root{
    --bg:#1e1e2e; --bg2:#181825; --card:#313244; --card-bd:#45475a;
    --text:#cdd6f4; --muted:#a6adc8; --dim:#6c7086;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
    font-family:"Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif;
    line-height:1.4;padding:24px 16px 60px}
  .wrap{max-width:1000px;margin:0 auto}
  .title-row{display:flex;align-items:baseline;justify-content:space-between;
    gap:12px;flex-wrap:wrap}
  h1{font-size:22px;margin:0 0 4px}
  .pack-count{color:var(--muted);font-size:13px;white-space:nowrap}
  .sub{color:var(--dim);font-size:13px;margin:0 0 20px}
  .tier{display:flex;gap:12px;margin:0 0 12px;background:var(--bg2);
    border:1px solid var(--card-bd);border-radius:12px;overflow:hidden}
  .tier-label{flex:0 0 auto;flex-shrink:0;display:flex;
    align-items:center;justify-content:center;font-weight:800;
    border-right:2px solid;padding:10px 10px;text-align:center;
    overflow-wrap:break-word;word-break:normal;line-height:1.15}
  .tier-packs{flex:1 1 auto;display:flex;flex-wrap:wrap;gap:8px;
    align-content:flex-start;align-items:flex-start;padding:10px}
  .pack{background:var(--card);border:1px solid var(--card-bd);border-radius:8px;
    max-width:260px;transition:border-color .15s, opacity .15s}
  .pack:hover{border-color:#89b4fa}
  .pack-link{display:block;padding:8px 12px;text-decoration:none;color:inherit}
  .pk-name{color:var(--text);font-weight:600;word-break:break-word}
  .pk-steam{vertical-align:-2px;margin-right:4px;flex-shrink:0}
  .pack:hover .pk-name{color:#89b4fa;text-decoration:underline}
  .pk-author{color:var(--muted);font-size:11px;margin-top:2px;word-break:break-word}
  .pk-diff{font-size:11px;font-weight:600;margin-top:4px}
  .pk-comment{color:var(--muted);font-size:12px;margin-top:4px;
    white-space:pre-wrap;word-break:break-word}
  .pk-tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
  .tag{font-size:11px;border:1px solid;border-radius:10px;padding:1px 8px}
  .pk-played{display:flex;align-items:center;gap:5px;font-size:11px;
    color:var(--dim);padding:0 12px 8px;cursor:pointer;user-select:none}
  .pk-played input{cursor:pointer;accent-color:#a6e3a1}
  .pack.played{opacity:.5}
  .pack.played .pk-name{text-decoration:line-through}
  .empty{color:var(--dim);font-size:12px;padding:6px 2px}
  @media (max-width:520px){
    .pack{max-width:none;flex:1 1 100%}
  }
</style>
</head>
<body>
  <div class="wrap">
    <div class="title-row">
      <h1>${title}</h1>
      <span class="pack-count">Пакетов: ${totalPacks}</span>
    </div>
    ${updatedHtml}
    ${tiersHtml || `<p class="sub">Тир-лист пуст.</p>`}
  </div>
  ${updatedScript}
  ${playedScript}
</body>
</html>`;
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS });
    }

    const url = new URL(request.url);
    const m = url.pathname.match(/^\/tier\/([A-Za-z0-9_-]{1,64})\/?$/);
    if (!m) {
      return json({ error: "not found" }, 404);
    }
    const id = m[1];
    const key = `tier:${id}`;

    if (request.method === "GET") {
      const raw = await env.TIER_KV.get(key);
      if (!raw) {
        return new Response("Тир-лист не найден или устарел.", {
          status: 404,
          headers: { "Content-Type": "text/plain; charset=utf-8", ...CORS },
        });
      }
      const rec = JSON.parse(raw);
      if (url.searchParams.get("format") === "json") {
        return json({ model: rec.model, updated: rec.updated });
      }
      return new Response(renderPage(rec.model || {}, rec.updated, id), {
        headers: { "Content-Type": "text/html; charset=utf-8", ...CORS },
      });
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
      const token = String(
        request.headers.get("X-Edit-Token") || body.token || ""
      ).slice(0, 128);
      if (!token) {
        return json({ error: "token required" }, 400);
      }

      const raw = await env.TIER_KV.get(key);
      if (raw) {
        const rec = JSON.parse(raw);
        if (rec.token && rec.token !== token) {
          return json({ error: "forbidden" }, 403);
        }
      }

      const model = {
        title: String(body.title || "").slice(0, 200),
        tiers: Array.isArray(body.tiers) ? body.tiers : [],
      };
      const updated = Number(body.updated) || Math.floor(Date.now() / 1000);
      await env.TIER_KV.put(
        key,
        JSON.stringify({ token, model, updated }),
        { expirationTtl: TTL_SECONDS }
      );
      return json({ ok: true, url: `${url.origin}/tier/${id}` });
    }

    return json({ error: "method not allowed" }, 405);
  },
};
