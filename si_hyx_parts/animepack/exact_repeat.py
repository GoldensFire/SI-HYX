# -*- coding: utf-8 -*-
"""Точные отпечатки вопросов готовых SIQ и новых кандидатов."""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[\w]+", text, re.UNICODE))


# Где в ответе кончается название и начинается сама песня: «… OP3 (2017) —
# 『WORLD END』». Отрезаем по тире ПЕРЕД кавычками, а не по первому попавшемуся:
# тире бывает и в самом названии («Код Гиас: Восставший Лелуш — Пробуждение»),
# и по первому тире от ответа оставался один огрызок без тега песни. Такой
# вопрос отпечатка «song» не получал вовсе и повторялся из пака в пак.
_SONG_TAIL = re.compile(r"\s[—–-]\s*[『«\"]")


def _song_key(answer: str) -> tuple | None:
    # Номер OP/ED сохраняем: OP10 и OP1 — разные вопросы.
    text = str(answer or "")
    cut = _SONG_TAIL.search(text)
    head = text[:cut.start()] if cut else text
    match = re.search(r"\b(OP\s*\d+|ED\s*\d+|OST\s*\d*)\b", head,
                      re.IGNORECASE)
    if not match:
        return None
    title = re.sub(r"\(\s*\d{4}\s*\)", "", head[:match.start()])
    return ("song", _norm(title), _norm(match.group(1)))


def _source_keys(answers: list[str]) -> set[tuple]:
    return {("source", text.strip().split("?", 1)[0].casefold())
            for text in answers if str(text or "").startswith(("https://", "http://"))
            and not any(host in str(text) for host in
                        ("youtube.com", "youtu.be", "fandom.com"))}


def _fact_key(question: str, answer: str) -> tuple | None:
    match = re.search(r"[«『]([^»』]+)[»』]", str(question or ""))
    if not match or not answer:
        return None
    # Заголовки сезонов могут отличаться; событие + ответ одной франшизы
    # остаются тем же сюжетным фактом.
    from animepack import title_root
    title = title_root(match.group(1))
    return ("plot-fact", title, _norm(answer)) if title else None


def _digest(stream) -> str:
    sha = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        sha.update(chunk)
    return sha.hexdigest()


def read_exact_keys(path: str) -> set[tuple]:
    """Читает только структуру и медиа вопросов, не распаковывая пакет."""
    keys: set[tuple] = set()
    try:
        with zipfile.ZipFile(path) as zf:
            xml_name = next((n for n in zf.namelist()
                             if n.lower().endswith("content.xml")), "")
            if not xml_name or zf.getinfo(xml_name).file_size > 20_000_000:
                return keys
            root = ET.fromstring(zf.read(xml_name))
            media = set(zf.namelist())
            for question in root.iter():
                if _local(question.tag) != "question":
                    continue
                answers, text, refs = [], "", []
                precise = False
                for node in question.iter():
                    tag = _local(node.tag)
                    if tag == "answer" and node.text:
                        answers.append(node.text.strip())
                    elif tag == "param" and node.get("name") == "question":
                        for item in node:
                            if _local(item.tag) != "item":
                                continue
                            if item.get("isRef") == "True" and item.text:
                                refs.append((item.get("type"), item.text.strip()))
                            elif item.text and item.get("placement") != "replic":
                                text = item.text.strip()
                if answers:
                    song = _song_key(answers[0])
                    if song:
                        keys.add(song)
                        precise = True
                    sources = _source_keys(answers)
                    keys.update(sources)
                    precise = precise or bool(sources)
                    if any("fandom.com" in value for value in answers):
                        fact = _fact_key(text, answers[0])
                        if fact:
                            keys.add(fact)
                            precise = True
                        elif text:
                            keys.add(("plot-text", _norm(text)))
                            precise = True
                if precise:
                    continue
                for kind, name in refs:
                    rel = {"audio": "Audio", "image": "Images",
                           "video": "Video"}.get(kind, "")
                    archive_name = f"{rel}/{name}" if rel else ""
                    if archive_name in media:
                        with zf.open(archive_name) as stream:
                            keys.add(("media", _digest(stream)))
    except (OSError, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile):
        return keys
    return keys


def candidate_keys(cand, folder: str) -> set[tuple]:
    """Отпечатки готового вопроса. Медиа уже записано в рабочую папку."""
    keys: set[tuple] = set()
    if cand.song and not cand.is_silent:
        song = _song_key(cand.main_answer)
        if song:
            keys.add(song)
    # Ссылка на работу Pixiv живёт в своём поле (art_link), а в ответ
    # готового пака идёт так же, как source_link. Без неё арт сравнивался
    # только хешем AVIF, а он у нового прогона свой, — и тот же арт повторялся
    # из пака в пак.
    keys.update(_source_keys([cand.source_link, cand.art_link]))
    if cand.plot_answers:
        fact = _fact_key(cand.plot_question, cand.plot_answers[0])
        if fact:
            keys.add(fact)
    elif cand.plot_question and cand.kind == "plot":
        keys.add(("plot-text", _norm(cand.plot_question)))
    if any(key[0] in ("song", "source", "plot-fact", "plot-text")
           for key in keys):
        return keys
    if cand.has_video:
        rel = ("Video", cand.video_out)
    elif cand.has_frame:
        rel = ("Images", cand.frame_file)
    elif not cand.is_silent:
        rel = ("Audio", cand.audio_out)
    else:
        rel = ("", "")
    if rel[0] and rel[1]:
        path = os.path.join(folder, *rel)
        try:
            with open(path, "rb") as stream:
                keys.add(("media", _digest(stream)))
        except OSError:
            pass
    return keys


def pixiv_links(keys) -> set[str]:
    """Страницы работ Pixiv, уже спрошенные в выбранных паках."""
    return {key[1] for key in keys
            if key[0] == "source" and "pixiv.net/" in key[1]}
