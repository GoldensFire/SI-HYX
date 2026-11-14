# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Прогон «Поиска по сабам»: тайтлы по порядку → файлы источников → фраза.

Для каждого тайтла сначала просматривается кэш (реплики уже скачанных
файлов — без сети, по любой новой фразе), затем докачиваются недостающие
файлы: по одному на серию раньше дублей других релизов, несколько потоков
сразу. Как только в тайтле нашлось совпадение (и хватает одного), остальные
его файлы не качаются. Каждый скачанный файл ложится в кэш, так что
следующий поиск — даже другой фразы — идёт по нему мгновенно.
"""
from __future__ import annotations

import hashlib
import re
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field


from . import corpus as corpus_mod
from .archives import iter_subtitle_files
from .http_client import Http, HttpError, Stopped
from .matcher import find_phrase, format_timecode, may_contain, prepare_cues, tokenize
from .parsers import filename_says_not_english, guess_episode, is_english, parse_subtitles
from .sources import AniZip, OpenSubtitles, QuotaExceeded, Subdl, SubSource, Tsdb
from .titles import ORDER_EASY, compute_rows, load_titles

SOURCE_LABELS = {"subdl": "SubDL", "subsource": "SubSource", "tsdb": "TSDB",
                 "opensubtitles": "OpenSubtitles"}
WORKERS = 4
MAX_MATCHES_PER_TITLE = 30


_EP_TAIL = re.compile(r"(?:^|E)(\d{1,4})$")


def _ep_num(ep) -> int | None:
    """Номер серии из «S01E05» / «05» / «5» (None — не серия)."""
    m = _EP_TAIL.search(str(ep or "").strip())
    return int(m.group(1)) if m else None


# Одна и та же реплика в разных релизах серии расходится по времени на секунды
# (TV/BD, сдвиг тайминга) — в этом окне совпадения считаются одним.
DUP_WINDOW_S = 10.0
_NON_WORD = re.compile(r"[\W_]+")


def _same_line_seen(state, episode_num, start: float, text: str) -> bool:
    """True — эта реплика этой серии уже есть среди совпадений тайтла
    (другой релиз), иначе запоминает её."""
    norm = _NON_WORD.sub(" ", str(text or "").lower()).strip()
    seen = state.setdefault("lines", [])
    for ep, at, other in seen:
        if ep == episode_num and other == norm and abs(at - float(start)) <= DUP_WINDOW_S:
            return True
    seen.append((episode_num, float(start), norm))
    return False


@dataclass
class SearchRequest:
    phrase: str = "six seven"
    max_titles: int = 5              # 0 — без цели, до конца списка
    order: str = ORDER_EASY
    level_min: int = 1
    level_max: int = 15
    kinds: tuple = ("tv", "movie", "ova", "special")
    sources: tuple = ("subdl", "subsource", "tsdb")
    cache_only: bool = False         # только уже скачанное, без сети
    max_gap: float = 3.0
    one_per_franchise: bool = True   # от франшизы — один найденный тайтл
    first_match_only: bool = True    # хватит одного совпадения на тайтл
    files_per_title: int = 0         # новых скачиваний на тайтл; 0 — без предела
    keys: dict = field(default_factory=dict)


@dataclass
class Hit:
    title: object                    # TitleInfo
    matches: list                    # [{episode, timecode, start, text, matched, …}]
    files_checked: int
    level: int = 0
    index: float = 0.0
    index_row: dict | None = None


class SearchEngine:
    """emit(event, data): status(str) · log(str) · progress((done, total)) ·
    hit(Hit) · finished(dict). is_excluded(list[TitleInfo]) → set(id) — исключение
    паков вкладки (зовётся из потока прогона)."""

    def __init__(self, req: SearchRequest, emit, stop: threading.Event | None = None,
                 excluded_ids=None) -> None:
        self.req = req
        self.emit = emit
        self.stop = stop or threading.Event()
        self.excluded_ids = excluded_ids
        self.tokens = tokenize(req.phrase)
        self.sources: dict = {}
        self.disabled: dict = {}
        self.stats = {"titles": 0, "files": 0, "downloads": 0, "cached": 0, "excluded": 0}

    # ── служебное ───────────────────────────────────────────────────────────
    def _stopped(self) -> bool:
        return self.stop.is_set()

    def _log(self, msg: str) -> None:
        self.emit("log", msg)

    def _disable(self, source: str, why: str) -> None:
        if source not in self.disabled:
            self.disabled[source] = why
            self._log(f"{SOURCE_LABELS.get(source, source)}: {why} — до конца поиска выключен.")
            wanted = set(self.req.sources)
            if not self.req.cache_only and wanted and wanted <= set(self.disabled):
                self._log("Все источники выключены — дальше проверяются только "
                          "уже скачанные сабы.")

    # ── прогон ──────────────────────────────────────────────────────────────
    def run(self) -> None:
        summary = {"found": 0, "stopped": False, "error": ""}
        if not self.tokens:
            summary["error"] = "введите фразу для поиска"
            self.emit("finished", summary)
            return
        self.corpus = corpus_mod.Corpus()
        self.http = Http(self.stop)
        try:
            found = self._run()
            summary["found"] = found
        except Stopped:
            summary["stopped"] = True
        except Exception as exc:  # noqa: BLE001 — показать во вкладке, не уронить поток
            summary["error"] = str(exc) or type(exc).__name__
        finally:
            summary["stopped"] = summary["stopped"] or self._stopped()
            summary.update(self.stats)
            summary["disabled"] = dict(self.disabled)
            self.http.close()
            self.corpus.close()
            self.emit("finished", summary)

    def _run(self) -> int:
        req = self.req
        pruned = self.corpus.prune()
        if pruned:
            self._log(f"Кэш: удалено устаревших файлов — {pruned}.")
        self.emit("status", "Читаю базу Shikimori…")
        titles, _by_id, _names = load_titles(req.kinds, req.level_min, req.level_max, req.order,
                                           self._stopped, self._log)
        if self._stopped():
            raise Stopped()
        self._setup_sources()

        if req.cache_only:
            have = self.corpus.cached_titles()
            titles = [t for t in titles if t.id in have]
            self._log(f"Только кэш: тайтлов со скачанными сабами — {len(titles)}.")
        if not titles:
            self._log("Под заданные условия не подходит ни один тайтл.")
            return 0

        excluded = set()
        if self.excluded_ids is not None:
            self.emit("status", "Применяю исключение паков…")
            excluded = set(self.excluded_ids(titles) or ())
        found_fr: set = set()
        found = 0
        total = len(titles)
        for n, t in enumerate(titles, 1):
            if self._stopped():
                raise Stopped()
            if req.max_titles and found >= req.max_titles:
                break
            self.emit("progress", (n - 1, total))
            if t.id in excluded:
                self.stats["excluded"] += 1
                continue
            if req.one_per_franchise and t.franchise and t.franchise in found_fr:
                continue
            lvl = f", уровень {t.level}" if t.level else ""
            self.emit("status", f"{n}/{total} · {t.anime.title}{lvl}")
            matches, checked = self._search_title(t)
            if checked:
                self.stats["titles"] += 1
            if not matches:
                continue
            found += 1
            if t.franchise:
                found_fr.add(t.franchise)
            row = compute_rows([t.id], self._stopped).get(t.id) or {}
            hit = Hit(t, matches, checked, int(row.get("level") or t.level or 0),
                      float(row.get("index") or 0.0), row or None)
            self.emit("hit", hit)
        self.emit("progress", (total, total))
        return found

    def _setup_sources(self) -> None:
        req, keys = self.req, self.req.keys
        anizip = AniZip(self.http, self.corpus)
        wanted = set(req.sources)
        if req.cache_only:
            return
        if "subdl" in wanted:
            if keys.get("subdl"):
                self.sources["subdl"] = Subdl(self.http, self.corpus, anizip, keys["subdl"])
            else:
                self._disable("subdl", "не задан ключ SubDL (Настройки → Ключи API)")
        if "subsource" in wanted:
            if keys.get("subsource"):
                self.sources["subsource"] = SubSource(self.http, self.corpus, anizip,
                                                      keys["subsource"])
            else:
                self._disable("subsource", "не задан ключ SubSource (Настройки → Ключи API)")
        if "tsdb" in wanted:
            self.sources["tsdb"] = Tsdb(self.http, self.corpus, anizip, keys.get("tsdb", ""))
        if "opensubtitles" in wanted:
            osub = OpenSubtitles(self.http, self.corpus, anizip,
                                 keys.get("opensubtitles", ""),
                                 keys.get("opensubtitles_user", ""),
                                 keys.get("opensubtitles_password", ""))
            if osub.configured:
                self.sources["opensubtitles"] = osub
            else:
                self._disable("opensubtitles",
                              "нужны ключ API, логин и пароль (Настройки → Ключи API)")

    # ── один тайтл ───────────────────────────────────────────────────────────
    def _scan(self, rows, state) -> bool:
        """Ищет фразу в репликах кэша; True — хватит (нашлось и нужен один)."""
        req = self.req
        if state["matches"] and req.first_match_only:
            # Нашлось раньше: файлы, докачанные параллельно (те же серии других
            # релизов), уже не нужны — иначе одна реплика повторялась 4 раза.
            return True
        for dl_key, source, url, member, episode, sha, blob in rows:
            if (dl_key, member) in state["seen"] or (sha and sha in state["sha"]):
                continue
            state["seen"].add((dl_key, member))
            if sha:
                state["sha"].add(sha)
            state["checked"] += 1
            self.stats["files"] += 1
            num = _ep_num(episode)
            if num is not None:
                state["eps"].add(num)
            try:
                text = corpus_mod.unpack_text(blob)
            except Exception:  # noqa: BLE001 — битая запись кэша
                continue
            if not may_contain(text.lower(), self.tokens):
                continue
            left = MAX_MATCHES_PER_TITLE - len(state["matches"])
            limit = 1 if req.first_match_only else max(1, left)
            for m in find_phrase(corpus_mod.cues_from_text(text), req.phrase,
                                 req.max_gap, limit=limit):
                if _same_line_seen(state, num, m.start, m.text):
                    continue   # та же реплика из другого релиза этой серии
                state["matches"].append({
                    "episode": episode, "start": m.start,
                    "timecode": format_timecode(m.start),
                    "text": m.text, "matched": m.matched, "kind": m.kind,
                    "source": source, "url": url,
                    "file": member.rsplit("!", 1)[-1],
                })
            if state["matches"] and (req.first_match_only
                                     or len(state["matches"]) >= MAX_MATCHES_PER_TITLE):
                return True
        return False

    def _candidates(self, t) -> list:
        out = []
        limit = self.req.files_per_title
        for name, src in self.sources.items():
            if name in self.disabled:
                continue
            try:
                out += src.candidates(t.id, t.card, limit * 2 if limit else 0)
            except Stopped:
                raise
            except QuotaExceeded as exc:
                self._disable(name, str(exc))
            except (HttpError, OSError, ValueError, KeyError, TypeError) as exc:
                self._log(f"{SOURCE_LABELS.get(name, name)} · {t.anime.title}: {exc}")
        out.sort(key=lambda c: c.rank)
        return out

    def _search_title(self, t):
        state = {"seen": set(), "sha": set(), "checked": 0, "matches": [], "eps": set()}
        cached = self.corpus.subs_for(t.id)
        self.stats["cached"] += len(cached)
        if self._scan(cached, state) or self.req.cache_only:
            return state["matches"], state["checked"]
        cands = self._candidates(t)
        todo = []
        for c in cands:
            if self.corpus.fresh_download(c.key):
                # Скачан раньше, возможно для другой части той же франшизы.
                self.corpus.link(t.id, [c.key])
                if self._scan(self.corpus.subs_of_download(c.key), state):
                    return state["matches"], state["checked"]
            else:
                # Тайтл уже проверен по кэшу: другая версия той же серии (или фильма,
                # файла без номера) фразу почти никогда не добавляет — не качаем.
                num = _ep_num(c.episode)
                if num in state["eps"] or (num is None and state["checked"]):
                    continue
                todo.append(c)
        if self.req.files_per_title:
            todo = todo[:self.req.files_per_title]
        if todo:
            self._download_and_scan(t, todo, state)
        return state["matches"], state["checked"]

    def _download_and_scan(self, t, todo: list, state) -> None:
        pending = list(todo)
        running = {}
        done_n = 0
        with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="subsearch") as pool:
            try:
                while pending or running:
                    while pending and len(running) < WORKERS and not self._stopped():
                        c = pending.pop(0)
                        if c.source in self.disabled:
                            continue
                        if c.episode and _ep_num(c.episode) in state["eps"]:
                            continue   # эту серию уже покрыл скачанный архив
                        running[pool.submit(self._fetch_one, t.id, c)] = c
                    if not running:
                        break
                    finished, _ = wait(list(running), timeout=0.5,
                                       return_when=FIRST_COMPLETED)
                    for fut in finished:
                        c = running.pop(fut)
                        done_n += 1
                        try:
                            fut.result()
                        except Stopped:
                            continue
                        except QuotaExceeded as exc:
                            self._disable(c.source, str(exc))
                            continue
                        self.emit("status", f"{t.anime.title}: файлов {done_n}/{len(todo)}")
                        if self._scan(self.corpus.subs_of_download(c.key), state):
                            pending.clear()   # нашлось — остальное не качаем
                    if self._stopped():
                        pending.clear()
            finally:
                for fut in running:
                    fut.cancel()
        if self._stopped():
            raise Stopped()

    def _fetch_one(self, shiki_id: int, c) -> None:
        """Скачивает и разбирает один файл/архив в кэш (поток пула)."""
        src = self.sources[c.source]
        try:
            data = src.fetch(c)
        except (Stopped, QuotaExceeded):
            raise
        except (HttpError, OSError, ValueError) as exc:
            self.corpus.store(c.key, c.source, c.public_url, c.name, corpus_mod.ERROR,
                              str(exc), [], shiki_id)
            return
        self.stats["downloads"] += 1
        notes: list = []
        members = []
        for member, blob in iter_subtitle_files(c.name if "." in c.name[-5:] else
                                                c.name + ".srt", data, notes):
            short = member.rsplit("!", 1)[-1]
            if filename_says_not_english(short):
                continue
            parsed = parse_subtitles(blob, short)
            if parsed is None:
                continue
            fmt, cues = parsed
            cues = prepare_cues(cues)
            ok, why = is_english(cues)
            if not ok:
                notes.append(f"{short}: {why}")
                continue
            if "!" in member:   # файл из архива — серия по его имени
                ep = guess_episode(short) or c.episode
            else:
                ep = c.episode or guess_episode(short)
            members.append((member, ep, fmt, hashlib.sha1(blob).hexdigest(),
                            corpus_mod.pack_cues(cues)))
        status = corpus_mod.OK if members else corpus_mod.NOT_ENGLISH
        self.corpus.store(c.key, c.source, c.public_url, c.name, status,
                          "; ".join(notes[:3]), members, shiki_id)


def run_search(req: SearchRequest, emit=None, stop=None, excluded_ids=None) -> list:
    """Прогон без интерфейса (для проверок и инструментов): список Hit."""
    hits = []

    def _emit(event, data):
        if event == "hit":
            hits.append(data)
        if emit:
            emit(event, data)

    SearchEngine(req, _emit, stop, excluded_ids).run()
    return hits

