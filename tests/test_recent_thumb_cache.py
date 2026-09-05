# -*- coding: utf-8 -*-
"""Кэш миниатюр ленты «последние файлы» и длительность из вывода ffmpeg.

Ради чего всё затевалось: на каждую из 30 карточек ленты запускалось ДВА
процесса (ffmpeg за кадром + ffprobe за длительностью), то есть до 60 запусков
215-мегабайтных бинарников при каждом старте программы. Теперь длительность
читается из stderr того же ffmpeg, а готовые миниатюры лежат на диске — со
второго запуска процессов нет вовсе.

Проверяется:
  • разбор строки «Duration:» и её формат на карточке;
  • запись/чтение кэша и то, что изменённый файл получает НОВЫЙ ключ (устаревшую
    картинку показать невозможно);
  • уборка кэша не даёт папке расти без предела.

Папка кэша подменена на временную (см. isolate_settings в conftest) — в
настоящий %APPDATA% пользователя тесты не пишут.
"""
import os
import time

import widgets


# ── Длительность из вывода ffmpeg ────────────────────────────────────────────
FFMPEG_LOG = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip.mp4':
  Metadata:
    major_brand     : isom
  Duration: 00:03:44.01, start: 0.000000, bitrate: 1737 kb/s
  Stream #0:0[0x1](und): Video: h264 (High), yuv420p, 1920x1080, 30 fps
"""


def test_duration_parsed_from_ffmpeg_stderr():
    assert widgets._duration_from_ffmpeg_log(FFMPEG_LOG) == 224.01


def test_duration_with_hours():
    log = "  Duration: 02:22:03.94, start: 0.000000, bitrate: 4127 kb/s"
    assert widgets._duration_from_ffmpeg_log(log) == 2 * 3600 + 22 * 60 + 3.94


def test_duration_absent_returns_zero():
    # Битый файл: ffmpeg длительность не печатает — вызывающий код обязан
    # увидеть 0 и уйти на запасной путь (ffprobe), а не показать «0:00».
    assert widgets._duration_from_ffmpeg_log("Invalid data found when processing input") == 0.0
    assert widgets._duration_from_ffmpeg_log("") == 0.0
    assert widgets._duration_from_ffmpeg_log(None) == 0.0


def test_duration_n_a_not_parsed():
    # Поток без известной длительности — ffmpeg пишет «Duration: N/A».
    assert widgets._duration_from_ffmpeg_log("  Duration: N/A, start: 0.000000") == 0.0


def test_fmt_duration_matches_old_ffprobe_labels():
    # Ровно те подписи, что рисовал прежний ffprobe-путь.
    assert widgets._fmt_duration(224.01) == "3:44"
    assert widgets._fmt_duration(8523.94) == "2:22:03"
    assert widgets._fmt_duration(9.06) == "0:09"
    assert widgets._fmt_duration(0) == ""
    assert widgets._fmt_duration(-1) == ""


# ── Кэш миниатюр ─────────────────────────────────────────────────────────────
def test_cache_round_trip(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"video-bytes")
    assert widgets._thumb_cache_read(str(f)) == (None, "")
    widgets._thumb_cache_write(str(f), b"\xff\xd8jpeg", "3:44")
    assert widgets._thumb_cache_read(str(f)) == (b"\xff\xd8jpeg", "3:44")


def test_cache_keeps_binary_payload_intact(tmp_path):
    # В картинке встречается и \n, и \x00 — заголовок отделяется ТОЛЬКО по
    # первому переводу строки, остальное обязано дойти байт в байт.
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    blob = b"\xff\xd8\n\x00\nPNG\n\xff"
    widgets._thumb_cache_write(str(f), blob, "")
    assert widgets._thumb_cache_read(str(f)) == (blob, "")


def test_changed_file_gets_new_key(tmp_path):
    """Файл переписали — ключ обязан смениться, иначе покажется чужой кадр."""
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"first")
    widgets._thumb_cache_write(str(f), b"first-thumb", "0:10")
    key_before = widgets._thumb_cache_key(str(f))

    time.sleep(1.1)                      # ключ берёт mtime с точностью до секунды
    f.write_bytes(b"second-and-longer")
    assert widgets._thumb_cache_key(str(f)) != key_before
    assert widgets._thumb_cache_read(str(f)) == (None, "")   # промах, пересчитаем


def test_missing_file_is_a_miss_not_a_crash(tmp_path):
    assert widgets._thumb_cache_read(str(tmp_path / "нет-такого.mp4")) == (None, "")


def test_empty_payload_is_not_written(tmp_path):
    """Кадр не получился — в кэш ничего не кладём: при следующем запуске
    попробуем снова (файл мог просто дочитываться)."""
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    widgets._thumb_cache_write(str(f), b"", "")
    assert widgets._thumb_cache_read(str(f)) == (None, "")
    assert not os.path.isdir(widgets._THUMB_CACHE_DIR) or \
        not os.listdir(widgets._THUMB_CACHE_DIR)


def test_trim_keeps_newest_and_runs_once(tmp_path, monkeypatch):
    monkeypatch.setattr(widgets, "_THUMB_CACHE_LIMIT", 5, raising=True)
    monkeypatch.setattr(widgets, "_thumb_cache_trimmed", False, raising=True)
    os.makedirs(widgets._THUMB_CACHE_DIR, exist_ok=True)
    for i in range(12):
        p = os.path.join(widgets._THUMB_CACHE_DIR, f"entry{i:02d}")
        with open(p, "wb") as fh:
            fh.write(b"x")
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))

    widgets._thumb_cache_trim()
    left = sorted(os.listdir(widgets._THUMB_CACHE_DIR))
    assert left == ["entry07", "entry08", "entry09", "entry10", "entry11"]

    # Второй вызов за запуск — уже пустышка: каталог не перечитывается.
    with open(os.path.join(widgets._THUMB_CACHE_DIR, "entry99"), "wb") as fh:
        fh.write(b"x")
    widgets._thumb_cache_trim()
    assert len(os.listdir(widgets._THUMB_CACHE_DIR)) == 6


# ── Ленивость yt-dlp ─────────────────────────────────────────────────────────
def test_ytdlp_is_not_imported_at_startup():
    """yt-dlp запускается процессом (bin\\yt-dlp.exe) — как ПАКЕТ он не нужен, а
    его импорт стоил ~340 мс на каждом запуске и тянул Cryptodome, curl_cffi,
    chardet и websockets. Если пакет снова понадобится — импортируйте лениво,
    внутри функции, а не на уровне модуля config."""
    import config
    assert not hasattr(config, "yt_dlp")
