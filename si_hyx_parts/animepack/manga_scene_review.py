# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Independently inspect the actual cropped pixels before saving a question."""
import base64
import hashlib
import io

from PIL import Image

from .visual_batch import request

MEMO_GROUP = "manga_scene_review_v7"
BATCH_MEMO_GROUP = "manga_single_panel_review_v1"
FIELDS = ("accept", "has_characters", "complete_character", "has_title_text",
          "large_blank_area", "fragmented", "cut_dialogue")
SCHEMA = {"type": "object", "properties": {
    **{key: {"type": "boolean"} for key in FIELDS},
    "character_description": {"type": "string"}, "reason": {"type": "string"},
    "characters": {"type": "array", "items": {"type": "object", "properties": {
        "description": {"type": "string"}, "face_complete": {"type": "boolean"},
        "edge_cut": {"type": "boolean"}},
        "required": ["description", "face_complete", "edge_cut"]}}},
    "required": [*FIELDS, "character_description", "characters", "reason"]}


def _parts(frame, expected, source_context=None):
    prompt = (
        "Проверь ГОТОВУЮ вырезку для викторины. Оцени только видимые пиксели. "
        "Назови в character_description реально видимого персонажа: лицо, "
        "волосы, одежда или поза; если его нет, оставь строку пустой. "
        "В characters ОБЯЗАТЕЛЬНО перечисли КАЖДОГО заметного персонажа "
        "готовой вырезки, включая второстепенных справа, слева и в соседней "
        "панели. Для каждого укажи расположение и реально видимые глаза, "
        "нос, рот в description; face_complete и edge_cut оцени отдельно. "
        "Если у края осталось пол-лица, отсутствуют нос или рот из-за "
        "обрезки, edge_cut=true и face_complete=false. Это относится и к "
        "обрезке в самом исходнике. Достаточно ОДНОГО такого персонажа "
        "для accept=false. Нельзя одобрять кадр только по главному герою. "
        "accept=true только если есть хорошо различимый персонаж и цельная "
        "сцена. complete_character=true означает: лицо хорошо читается "
        "целиком у КАЖДОГО заметного персонажа. Если у одного из двух "
        "персонажей обрезаны глаза или лицо, complete_character=false, "
        "даже когда второй виден целиком. Обычный портрет по грудь допустим. "
        "Проверь КАЖДУЮ видимую панель отдельно: панель с одним ртом или "
        "подбородком делает fragmented=true, даже если ниже есть целое лицо. "
        "Крупный портрет с волосами за верхним краем исходной панели допустим, "
        "если видны все естественно видимые глаза, нос и рот. Не требуй всю "
        "причёску или тело у такого портрета; у профиля один глаз допустим. "
        "Один рот/подбородок, макушка или обрезанное краем лицо не годятся. "
        "cut_dialogue=true если край вырезки срезает хотя бы одно слово, "
        "строку, облачко реплики или текстовую плашку. Реплики обязательны "
        "целиком, включая части на белом поле за рамкой рисунка. "
        "В этом случае accept=false. "
        "Одни реплики, пустота, пейзаж, руки или мелкий силуэт не годятся. "
        "large_blank_area=true если пустые белые/чёрные поля или "
        "промежутки без рисунка и текста занимают больше четверти кадра. "
        "Цельные реплики этой сцены на белом поле не являются пустотой. "
        "Даже если внизу есть персонаж, верхняя половина из одних реплик "
        "или пустоты делает вырезку НЕПРИГОДНОЙ. Маленькие поля допустимы. "
        "fragmented=true если видны обрубки соседних панелей вместо цельной "
        "сцены. has_title_text=true только при видимом названии произведения "
        "(включая рекламу/титры), а не названии сайта или обычном диалоге. "
        "Ожидаемое произведение: " + expected + ". Причина кратко по-русски.")
    parts = [{"type": "text", "text": prompt}]
    if source_context is not None:
        parts.extend([{"type": "text", "text": (
            "ИСХОДНЫЙ КОНТЕКСТ той же сцены для сравнения с вырезкой ниже. "
            "Проверь, что вырезка сохранила весь рисунок выбранной панели, "
            "все лица и все её реплики. Если в вырезке исчезла часть реплики "
            "или реплика целиком, cut_dialogue=true. Соседние панели в "
            "контексте не обязаны входить в вырезку.")}, _image(source_context)])
    parts.extend([{"type": "text", "text": "ГОТОВАЯ ВЫРЕЗКА — оцени её:"},
                  _image(frame)])
    return parts


def _key(client, parts):
    payload = "".join(str(part.get("text") or part.get("data")) for part in parts)
    return f"{client.model}:{hashlib.sha256(payload.encode()).hexdigest()}"


def check(generator, frame, expected, *, source_context=None):
    parts = _parts(frame, expected, source_context)
    client = generator.gemini_manga
    key = _key(client, parts)
    verdict = generator.db_cache.memo(MEMO_GROUP, key)
    if verdict is None:
        verdict = request(generator, client, parts, SCHEMA)
        if isinstance(verdict, dict):
            generator.db_cache.remember_memo(MEMO_GROUP, key, verdict)
    return _accepted(verdict)


def check_many(generator, scenes, expected):
    """Review all proposed crops in one request, reusing individual verdicts."""
    client = generator.gemini_manga
    answers, pending = [None] * len(scenes), []
    parts = [{"type": "text", "text": (
        "Проверь все вырезки scene_id независимо. Верни scenes с вердиктом "
        "для КАЖДОГО scene_id. accept в корне — есть ли хотя бы один "
        "пригодный вариант; has_title_text в корне — есть ли название "
        "хотя бы на одном. Не переноси достоинства одной сцены на другую. "
        "Укажи panel_count — число отдельных панелей с рисунком в ГОТОВОЙ "
        "вырезке, без исходного контекста. Облачки не считаются панелями. "
        "Пригодна ровно ОДНА цельная панель. Участок с одними глазами или "
        "ртом считается отдельной обрезанной панелью, даже если тот же "
        "персонаж виден целиком в другой панели.")}]
    for index, (frame, context) in enumerate(scenes):
        content = _parts(frame, expected, context)
        key = _key(client, content)
        saved = generator.db_cache.memo(BATCH_MEMO_GROUP, key)
        if saved is not None:
            answers[index] = _batch_accepted(saved)
            continue
        pending.append((index, key))
        parts.append({"type": "text", "text": f"Вырезка scene_id={index}"})
        parts.extend(content)
    if pending:
        item = dict(SCHEMA, properties={**SCHEMA["properties"],
                                       "scene_id": {"type": "integer"},
                                       "panel_count": {"type": "integer"}},
                    required=[*SCHEMA["required"], "scene_id", "panel_count"])
        schema = {"type": "object", "properties": {
            "accept": {"type": "boolean"}, "has_title_text": {"type": "boolean"},
            "reason": {"type": "string"},
            "scenes": {"type": "array", "items": item}},
            "required": ["accept", "has_title_text", "reason", "scenes"]}
        response = request(generator, client, parts, schema)
        rows = response.get("scenes") if isinstance(response, dict) else None
        expected_ids = {index for index, _ in pending}
        valid = (isinstance(rows, list) and len(rows) == len(pending)
                 and all(isinstance(row, dict) and type(row.get("scene_id")) is int
                         for row in rows)
                 and {row["scene_id"] for row in rows} == expected_ids)
        found = {row["scene_id"]: row for row in rows} if valid else {}
        for index, key in pending:
            verdict = found.get(index, {})
            if verdict:
                generator.db_cache.remember_memo(BATCH_MEMO_GROUP, key, verdict)
            answers[index] = _batch_accepted(verdict)
    return answers


def _batch_accepted(verdict):
    good, reason = _accepted(verdict)
    count = verdict.get("panel_count") if isinstance(verdict, dict) else None
    if type(count) is not int or count != 1:
        return False, "нужна одна цельная панель без вставок с обрезанными лицами"
    return good, reason


def _accepted(verdict):
    verdict = verdict if isinstance(verdict, dict) else {}
    characters = verdict.get("characters")
    complete_faces = (isinstance(characters, list) and bool(characters)
                      and all(isinstance(person, dict)
                              and person.get("face_complete") is True
                              and person.get("edge_cut") is False
                              and bool(str(person.get("description") or "").strip())
                              for person in characters))
    good = (all(verdict.get(k) is True for k in
                ("accept", "has_characters", "complete_character"))
            and all(verdict.get(k) is False for k in
                    ("has_title_text", "large_blank_area", "fragmented", "cut_dialogue"))
            and bool(str(verdict.get("character_description") or "").strip())
            and complete_faces)
    return good, str(verdict.get("reason") or "нет цельной сцены с персонажем")


def _image(picture):
    preview = picture.copy()
    preview.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    preview.save(output, "JPEG", quality=92)
    return {"type": "image", "mime_type": "image/jpeg",
            "data": base64.b64encode(output.getvalue()).decode("ascii")}
