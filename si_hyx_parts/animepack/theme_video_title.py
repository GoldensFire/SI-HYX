# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Нет ли прямо на отрезке опенинга/эндинга названия тайтла.

Вопрос с видеорядом угадывают по картинке, а в опенингах название часто стоит
прямо в кадре — логотип в начале или в конце ролика. Такой отрезок раскрывает
ответ (просьба пользователя). Из готового отрезка берутся кадры с шагом в
полторы секунды, локальный OCR сверяет надписи со всеми названиями тайтла (тем
же сравнением, что у страниц манги и артов Pixiv), а сомнительные кадры
досматривает Gemini, если она подключена. Нашлось название — генератор берёт
другой отрезок того же ролика (theme_video.download_video)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import animepack as api

# Кадров на отрезок: логотип держится на экране секунду-две, при отрезке в
# 15 с шаг в полторы секунды его не пропускает.
SAMPLES = 10
# Отрезков одного ролика, если на прежних видно название тайтла.
CLIP_ATTEMPTS = 3
# Сколько сомнительных кадров одного отрезка досматривает Gemini: титры
# опенинга на японском OCR не читает, и без предела каждый ролик тратил бы
# квоту на десяток запросов.
GEMINI_FRAMES = 2


def _frames(generator, path, seconds) -> list[bytes]:
    with tempfile.TemporaryDirectory(prefix="_title_", dir=generator.folder) as folder:
        pattern = str(Path(folder) / "f_%02d.png")
        rate = SAMPLES / max(1.0, float(seconds))
        command = [api.FFMPEG, "-y", "-v", "error", "-i", str(path),
                   "-vf", f"fps={rate:.4f},scale=-2:'min(720,ih)'",
                   "-frames:v", str(SAMPLES), pattern]
        code, _error = generator._run_killable(command, timeout=120)
        if code:
            return []
        return [item.read_bytes() for item in sorted(Path(folder).glob("f_*.png"))]


def _gemini_says_title(generator, candidate, data) -> str:
    """Причина отказа по вердикту Gemini («» — названия нет или спросить нельзя)."""
    if getattr(generator, "gemini_frames", None) is None:
        return ""
    from .frame_visual_check import check
    try:
        verdict = check(generator, candidate, data, ".png",
                        purpose="проверка видеоряда")
    except Exception as error:  # noqa: BLE001 — без Gemini отрезок не бракуем
        generator._log_rare("Проверка видеоряда Gemini", str(error))
        return ""
    if verdict.get("has_title_text"):
        return "Gemini: " + (str(verdict.get("reason") or "").strip()
                             or "на кадре видно название")
    return ""


def title_on_screen(generator, candidate, path) -> str:
    """Причина отказа отрезка: на нём видно название («» — не видно)."""
    from .local_title_match import decide, titles
    from .local_visual_ocr import note, read
    names = titles(candidate.anime or {})
    if not names:
        return ""
    seconds = max(3, int(generator.s.video_cut))
    unsure = []
    for data in _frames(generator, path, seconds):
        if generator.stopped():
            return ""
        try:
            rows, elapsed, cached = read(generator, data)
        except Exception as error:  # noqa: BLE001 — нет моделей OCR
            if generator.stopped():
                return ""
            generator._log_rare("OCR видеоряда", f"недоступен ({error}) — "
                                "название на видео не проверено")
            return ""
        result = decide(rows, names)
        if result["status"] == "title":
            note(generator, "видеоряда", result, elapsed, cached, False)
            return f"OCR: «{result['ocr']}» = «{result['title']}»"
        if result["status"] == "uncertain":
            # Похожая на название надпись важнее нечитаемой (титры на японском).
            unsure.append((not result["title"], data))
    unsure.sort(key=lambda item: item[0])
    for _plain, data in unsure[:GEMINI_FRAMES]:
        if generator.stopped():
            return ""
        reason = _gemini_says_title(generator, candidate, data)
        if reason:
            return reason
    return ""


def download_clean_video(generator, candidate) -> bool:
    """Отрезок ролика без названия тайтла в кадре (False — ролика не будет).

    Отрезок начинается со случайной секунды (_video_start), поэтому повтор
    берёт другое место того же ролика."""
    for attempt in range(1, CLIP_ATTEMPTS + 1):
        if not generator.download_video(candidate):
            return False
        path = Path(generator.folder) / "Video" / candidate.video_out
        reason = title_on_screen(generator, candidate, path)
        if not reason:
            return True
        candidate.has_video = candidate.theme_video_ready = False
        path.unlink(missing_ok=True)
        if generator.stopped():
            return False
        more = (f" — беру другой отрезок ({attempt + 1}/{CLIP_ATTEMPTS})"
                if attempt < CLIP_ATTEMPTS else " — видео не беру")
        generator.log(f"Ролик «{candidate.title_ru}»: на видео видно название "
                      f"({reason}){more}.")
    return False
