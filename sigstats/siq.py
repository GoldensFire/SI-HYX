"""Скачивание и разбор .siq (это ZIP с content.xml внутри).

Опциональная часть: нужна только если включено скачивание пакетов. Достаёт
тексты вопросов, ответы и медиаконтент. Поддерживает формат v4 (scenario/atom)
и v5 (params/item). Медиа извлекается в media/<package_id>/.
"""
from __future__ import annotations
import io
import json as _json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import unquote

import requests

from . import config
from .normalize import normalize_theme, display_theme
import siq_duration

# тип атома → папка медиа в архиве
_MEDIA_FOLDER = {"image": "Images", "voice": "Audio", "audio": "Audio",
                 "video": "Video", "html": "Html"}
_MEDIA_TYPES = set(_MEDIA_FOLDER)
_CONTENT_CANDIDATES = ("content.xml", "Content.xml")

# ── Оценка длительности пакета (правила группировки — см. siq_duration.py) ────
_CHARS_PER_SEC = siq_duration.CHARS_PER_SEC     # скорость чтения текста
_IMAGE_SEC = siq_duration.IMAGE_SEC             # показ одной картинки
_FFPROBE_CACHED: str | None = None


def _ffprobe() -> str | None:
    """Путь к ffprobe: сначала config.FFPROBE_PATH (хост-приложение может
    подставить свой bundled-бинарник — см. sigstats_tab.py), иначе системный
    PATH. Лениво — FFPROBE_PATH выставляется хостом ПОСЛЕ импорта этого модуля."""
    global _FFPROBE_CACHED
    if _FFPROBE_CACHED is None:
        _FFPROBE_CACHED = config.FFPROBE_PATH or shutil.which("ffprobe") or ""
    return _FFPROBE_CACHED or None


_DURATION_CACHE: dict[str, float | None] = {}   # путь → секунды (на время процесса)


def _probe_duration(path: Path | str) -> float | None:
    """Длительность аудио/видео в секундах (ffprobe → mutagen → None)."""
    key = str(path)
    if key in _DURATION_CACHE:
        return _DURATION_CACHE[key]
    dur: float | None = None
    ffprobe = _ffprobe()
    if ffprobe:
        try:
            out = subprocess.run(
                [ffprobe, "-v", "quiet", "-print_format", "json",
                 "-show_format", key],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                creationflags=config.CREATE_NO_WINDOW)
            data = _json.loads(out.stdout or "{}")
            d = data.get("format", {}).get("duration")
            dur = float(d) if d is not None else None
        except Exception:
            dur = None
    if dur is None:
        try:
            import mutagen
            mf = mutagen.File(key)
            if mf is not None and mf.info is not None:
                dur = float(mf.info.length)
        except Exception:
            dur = None
    _DURATION_CACHE[key] = dur
    return dur


_ANSWER_TEXT_SEC = siq_duration.ANSWER_TEXT_SEC  # обычный текстовый ответ
# Современные («тяжёлые») кодеки — за них небольшой бонус
_MODERN_CODECS = {"hevc", "h265", "av1", "vvc", "h266"}

_CODEC_CACHE: dict[str, str | None] = {}


def probe_video_codec(path: Path | str) -> str | None:
    """Кодек видео (ffprobe, codec_name): h264 / hevc / av1 / vvc …"""
    key = str(path)
    if key in _CODEC_CACHE:
        return _CODEC_CACHE[key]
    codec = None
    ffprobe = _ffprobe()
    if ffprobe:
        try:
            out = subprocess.run(
                [ffprobe, "-v", "quiet", "-print_format", "json",
                 "-show_streams", "-select_streams", "v:0", key],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                creationflags=config.CREATE_NO_WINDOW)
            streams = _json.loads(out.stdout or "{}").get("streams", [])
            if streams:
                codec = (streams[0].get("codec_name") or "").lower() or None
        except Exception:
            codec = None
    _CODEC_CACHE[key] = codec
    return codec


def _has_modern_video(*media_lists) -> bool:
    """Есть ли среди медиа видео с современным кодеком (hevc/av1/vvc)."""
    for ml in media_lists:
        for m in ml or []:
            if m.get("type") == "video" and m.get("path"):
                if (probe_video_codec(m["path"]) or "") in _MODERN_CODECS:
                    return True
    return False


_DIM_CACHE: dict[str, tuple[int, int] | None] = {}


def media_dimensions(path: Path | str) -> tuple[int, int] | None:
    """(ширина, высота) видео/картинки через ffprobe; None если не удалось."""
    key = str(path)
    if key in _DIM_CACHE:
        return _DIM_CACHE[key]
    dims = None
    ffprobe = _ffprobe()
    if ffprobe:
        try:
            out = subprocess.run(
                [ffprobe, "-v", "quiet", "-print_format", "json",
                 "-show_streams", "-select_streams", "v:0", key],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                creationflags=config.CREATE_NO_WINDOW)
            streams = _json.loads(out.stdout or "{}").get("streams", [])
            if streams:
                w = int(streams[0].get("width") or 0)
                h = int(streams[0].get("height") or 0)
                if w and h:
                    dims = (w, h)
        except Exception:
            dims = None
    _DIM_CACHE[key] = dims
    return dims


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el, name: str):
    return [c for c in el if _local(c.tag) == name]


def _child(el, name: str):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def download_siq(session: requests.Session, sibrowser_id: str, name_hint: str,
                 progress_cb=None, should_stop=None) -> Path | None:
    """Качает .siq через direct_download (следует за редиректом на хранилище).

    progress_cb(done_bytes, total_bytes) — необязательный колбэк прогресса
    скачивания (для показа процента в интерфейсе). total_bytes == 0, если сервер
    не прислал Content-Length.

    should_stop() — необязательная проверка отмены, вызывается между чанками
    (не только между паками, как у остальных collector-функций): без неё
    отмена скачивания срабатывала только ПОСЛЕ полного докачивания текущего
    файла — на большом .siq это выглядело как «отмена не работает».
    """
    config.ensure_dirs()
    stop = should_stop or (lambda: False)
    safe = re.sub(r"[^\w\-. ]+", "_", name_hint)[:80].strip() or sibrowser_id
    dest = config.PACKAGES_DIR / f"{sibrowser_id}_{safe}.siq"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = f"{config.SIBROWSER_BASE}/packages/{sibrowser_id}/direct_download"
    tmp = dest.with_suffix(".part")
    try:
        with session.get(url, timeout=config.REQUEST_TIMEOUT, stream=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            cancelled = False
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if stop():
                        cancelled = True
                        break
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if progress_cb is not None:
                            try:
                                progress_cb(done, total)
                            except Exception:
                                pass
            if cancelled:
                tmp.unlink(missing_ok=True)
                return None
            tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        return None
    return dest


def _extract_atom(zf: zipfile.ZipFile, atype: str, raw: str,
                  media_dir: Path) -> dict | None:
    """Возвращает запись о медиа: {type, ref, embedded, path|url}."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("@"):
        fname = unquote(raw[1:])
        folder = _MEDIA_FOLDER.get(atype, "Images")
        entry = f"{folder}/{fname}"
        # имя в архиве часто percent-кодировано (Video/%D0%9F…mp4), а ссылка —
        # в декодированном виде. Сравниваем, декодируя имена из архива.
        names = zf.namelist()
        match = None
        for n in names:
            dec = unquote(n)
            if n == entry or dec == entry or dec.endswith("/" + fname) \
                    or n.endswith("/" + fname) or _local(dec) == fname:
                match = n
                break
        out_path = None
        if match:
            try:
                data = zf.read(match)
                media_dir.mkdir(parents=True, exist_ok=True)
                out = media_dir / fname
                out.write_bytes(data)
                out_path = str(out)
            except Exception:
                out_path = None
        return {"type": atype, "ref": fname, "embedded": True, "path": out_path}
    if raw.startswith("http"):
        return {"type": atype, "ref": raw, "embedded": False, "path": None}
    # просто текстовое содержимое неизвестного типа — не медиа
    return None


def _parse_dur_attr(s: str | None) -> float | None:
    """Разбирает атрибут duration: «5», «5.0», «mm:ss», «hh:mm:ss»."""
    return siq_duration.parse_dur_attr(s)


def _item_info(item_el) -> dict:
    """Структурированный элемент контента (для длительности и медиа)."""
    atype = (item_el.get("type") or "text").lower()
    if atype == "voice":
        atype = "audio"
    return {
        "type": atype,
        "raw": (item_el.text or "").strip(),
        "is_ref": (item_el.get("isRef") or "").lower() == "true",
        "wait_false": (item_el.get("waitForFinish") or "").lower() == "false",
        "placement": (item_el.get("placement") or "").lower(),
        "dur_attr": _parse_dur_attr(item_el.get("duration")),
    }


def _item_seconds(info: dict, zf, media_dir) -> float:
    """Длительность одного элемента по правилам пользователя.

    Если на элементе стоит таймер (атрибут duration) — длительность берётся
    ровно по таймеру, независимо от типа и реальной длины медиа (видео на 30 с
    с таймером 26 с считается как 26 с).
    """
    if info["dur_attr"] is not None:
        return max(0.0, float(info["dur_attr"]))
    t = info["type"]
    if t == "image":
        return _IMAGE_SEC
    if t == "html":
        # No reliable way to know how long an interactive minigame runs —
        # treat it like a static image unless an explicit timer is set.
        return _IMAGE_SEC
    if t in ("audio", "video"):
        m = _extract_atom(zf, t, ("@" + info["raw"]) if info["is_ref"] else info["raw"],
                          media_dir)
        path = m and m.get("path")
        d = _probe_duration(path) if path else None
        return float(d) if d else 0.0
    # текст / say
    return len(info["raw"]) / _CHARS_PER_SEC if info["raw"] else 0.0


def _content_duration(items: list[dict], zf, media_dir) -> float:
    """Длительность последовательности элементов с учётом одновременного показа
    (группировка — см. siq_duration.content_duration; тут только пробрасываем
    ffprobe-специфичный способ измерить один элемент)."""
    return siq_duration.content_duration(
        items, lambda it: _item_seconds(it, zf, media_dir))


def _scenario_items(scenario, half: str) -> list[dict]:
    """Атомы v4 до/после marker как унифицированные элементы (всё последовательно)."""
    out: list[dict] = []
    before = True
    for atom in _children(scenario, "atom"):
        atype = (atom.get("type") or "text").lower()
        if atype == "marker":
            before = False
            continue
        if (half == "question") != before:
            continue
        if atype == "voice":
            atype = "audio"
        out.append({"type": atype, "raw": (atom.text or "").strip(),
                    "is_ref": (atom.text or "").strip().startswith("@"),
                    "wait_false": False, "placement": "",
                    "dur_attr": None})
    return out


def _extract_media_from_infos(infos: list[dict], zf, media_dir) -> tuple[list[dict], list[str]]:
    """Из списка элементов достаёт медиа (с извлечением файлов) и тексты."""
    media: list[dict] = []
    texts: list[str] = []
    for info in infos:
        if info["type"] in _MEDIA_TYPES:
            ref = ("@" + info["raw"]) if info["is_ref"] else info["raw"]
            m = _extract_atom(zf, info["type"], ref, media_dir)
            if m:
                media.append(m)
        elif info["raw"]:
            texts.append(info["raw"])
    return media, texts


def _parse_question(q_el, zf, media_dir) -> tuple[str, list[dict], list[dict], float]:
    """Текст вопроса + медиа вопроса + медиа ответа + оценка длительности.

    Понимает scenario/atom (v4) и params/item (v5). Длительность считается по
    контенту вопроса, контенту ответа («сложный ответ») и тексту правильного
    ответа (20 симв/сек) с учётом одновременного показа. Медиа «сложного ответа»
    возвращается отдельно, чтобы показать его под ответом.
    """
    texts: list[str] = []
    media: list[dict] = []
    answer_media: list[dict] = []
    q_items: list[dict] = []
    a_items: list[dict] = []
    # «время на ответ»: таймер на вопросе целиком или на блоке ответа
    answer_time = _parse_dur_attr(q_el.get("duration"))

    scenario = _child(q_el, "scenario")
    if scenario is not None:
        q_items = _scenario_items(scenario, "question")
        a_items = _scenario_items(scenario, "answer")
        media, texts = _extract_media_from_infos(q_items, zf, media_dir)
        answer_media, _ = _extract_media_from_infos(a_items, zf, media_dir)

    params = _child(q_el, "params")
    if params is not None:
        for param in _children(params, "param"):
            pname = (param.get("name") or "").lower()
            items = _children(param, "item") or [param]
            infos = [_item_info(it) for it in items]
            if pname == "question":
                q_items = infos
                media, texts = _extract_media_from_infos(infos, zf, media_dir)
            elif pname == "answer":
                a_items = infos
                answer_media, _ = _extract_media_from_infos(infos, zf, media_dir)
                if answer_time is None:
                    answer_time = _parse_dur_attr(param.get("duration"))

    # есть ли «сложный ответ» (контент-ответ с текстом/медиа)
    has_answer_content = any(it.get("raw") or it.get("type") in _MEDIA_TYPES
                             for it in a_items)
    dur = siq_duration.question_duration(
        q_items, a_items, answer_time, has_answer_content,
        bool(_answer_texts(q_el)), lambda it: _item_seconds(it, zf, media_dir))
    return (" ".join(texts).strip(), media, answer_media, round(dur, 2))


def _answer_texts(q_el) -> list[str]:
    """Список правильных ответов из <right> по порядку."""
    right = _child(q_el, "right")
    out = []
    if right is not None:
        for ans in _children(right, "answer"):
            if ans.text and ans.text.strip():
                out.append(ans.text.strip())
    return out


def _parse_answer(q_el) -> str:
    return " / ".join(_answer_texts(q_el))


def read_package_name(path) -> str | None:
    """Внутреннее имя пакета из content.xml (атрибут <package name>)."""
    try:
        with zipfile.ZipFile(path) as zf:
            cname = next((n for n in _CONTENT_CANDIDATES if n in zf.namelist()), None)
            if not cname:
                cname = next((n for n in zf.namelist()
                              if n.lower().endswith("content.xml")), None)
            if not cname:
                return None
            root = ET.fromstring(zf.read(cname))
            return root.get("name")
    except Exception:
        return None


def parse_siq(path: Path, package_id: int) -> tuple[list[dict], list[dict]]:
    """Возвращает (themes, questions) из .siq. Медиа кладёт в media/<package_id>/."""
    media_dir = config.MEDIA_DIR / str(package_id)
    with zipfile.ZipFile(path) as zf:
        cname = next((n for n in _CONTENT_CANDIDATES if n in zf.namelist()), None)
        if not cname:
            cname = next((n for n in zf.namelist()
                          if n.lower().endswith("content.xml")), None)
        if not cname:
            return [], []
        root = ET.fromstring(zf.read(cname))
        rounds_el = _child(root, "rounds")
        if rounds_el is None:
            return [], []

        themes_out: list[dict] = []
        questions_out: list[dict] = []
        for r_idx, rnd in enumerate(_children(rounds_el, "round")):
            round_name = rnd.get("name") or f"Раунд {r_idx + 1}"
            themes_container = _child(rnd, "themes")
            if themes_container is None:
                continue
            for t_idx, theme in enumerate(_children(themes_container, "theme")):
                tname = theme.get("name") or ""
                themes_out.append({
                    "round_index": r_idx,
                    "round_name": round_name,
                    "theme_index": t_idx,
                    "name": display_theme(tname),
                    "name_norm": normalize_theme(tname),
                    "source": "siq",
                })
                q_container = _child(theme, "questions")
                if q_container is None:
                    continue
                for q_idx, q in enumerate(_children(q_container, "question")):
                    price = q.get("price")
                    text, media, answer_media, dur = _parse_question(q, zf, media_dir)
                    answer = " / ".join(_answer_texts(q))
                    questions_out.append({
                        "round_index": r_idx,
                        "theme_index": t_idx,
                        "question_index": q_idx,
                        "price": int(price) if price and price.isdigit() else None,
                        "text": text,
                        "answer": answer,
                        "media": media,
                        "answer_media": answer_media,
                        "duration_sec": round(dur, 2),
                        "video_modern": _has_modern_video(media, answer_media),
                    })
        return themes_out, questions_out
