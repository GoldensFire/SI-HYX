# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# avif_fit.py — кодирование картинки в AVIF под лимит размера (libaom-av1).
# Здесь НЕТ Qt: модуль общий для вкладки «Обработка» (workers.ProcessWorker,
# оттуда логика и переехала) и генератора аниме-паков (animepack.py), чтобы
# флаги кодера и стратегия подбора CQ не разъезжались между ними.
from __future__ import annotations

import math
import os
import subprocess
import time
import uuid
from typing import Optional

try:
    from config import CREATE_NO_WINDOW, FFMPEG, TEMP_DIR
except Exception:  # pragma: no cover — модуль должен жить и без приложения
    import tempfile
    FFMPEG, CREATE_NO_WINDOW, TEMP_DIR = "ffmpeg", 0, tempfile.gettempdir()

# Диапазон CQ у libaom: 0 — максимальное качество, 63 — минимальное.
CQ_BEST, CQ_WORST = 0, 63
# Цель поиска берётся чуть НИЖЕ лимита: на гладкой кривой интерполяция к самому
# лимиту почти всегда промахивается вверх, и проход теряется впустую.
_TARGET_BIAS = 0.9


def avif_pix_fmt(has_alpha: bool, chroma: str = "420") -> str:
    """pix_fmt для AVIF по выбранной цветовой субдискретизации. Всегда 10 бит:
    у AV1 это дешевле по битрейту и убирает бандинг на градиентах."""
    if has_alpha:
        return "yuva420p10le"
    return {"444": "yuv444p10le", "422": "yuv422p10le"}.get(str(chroma), "yuv420p10le")


def avif_encode_cmd(src, tmp_out, crf_val, scale_vf, has_alpha, pix_fmt, aspd):
    """Команда ffmpeg для одного кодирования картинки в AVIF (libaom-av1).

    tune=iq («Image Quality») — режим тюнинга libaom именно под неподвижные
    изображения; передаётся через -aom-params, т.к. ffmpeg-обёртка -tune
    знает только psnr/ssim. Проверено: -aom-params валидирует ключи по-
    настоящему (bogus-значение роняет открытие энкодера), так что принятый
    tune=iq — реально применяемый режим, не тихая заглушка.

    has_alpha=True: цвет (yuva420p10le) и извлечённая альфа (gray10le) идут
    двумя av1-потоками, avif-муксер сшивает их в файл с прозрачностью.
    ВАЖНО: split ДО scale — если масштабировать перед split, ffmpeg при
    согласовании форматов роняет альфу (alphaextract «could not choose
    format»). Поэтому делим из yuva420p10le, затем масштабируем каждую
    ветку отдельно (цвет и альфа одного размера)."""
    # -usage allintra — режим libaom «только внутрикадровое кодирование», ровно
    # то, чем и является одиночная картинка.
    #
    # Замеры на живых картинках Shikimori (подбор CQ под 150 КБ, ssim/psnr
    # против оригинала):
    #   кадр 1280×720   good@8 0,55 с psnr 52,97 │ allintra@8 0,09 с psnr 52,30
    #   постер 685×975  good@8 1,40 с psnr 45,47 │ allintra@8 0,26 с psnr 44,91
    # То есть при ОДИНАКОВОМ -cpu-used allintra впятеро-вшестеро быстрее и
    # отдаёт за это примерно полдецибела. Но время можно вернуть в качество:
    #   кадр   allintra@4 0,49 с psnr 52,97 — ровно как good@8, и всё равно быстрее
    #   постер allintra@6 0,31 с psnr 45,66 — ЛУЧШЕ good@8 вчетверо быстрее
    # Поэтому режим включён всегда: при равном времени он выигрывает, а при
    # равной скорости разница в полдецибела на 45-53 дБ незаметна глазом.
    #
    # Старые сборки ffmpeg этого значения не знают — тогда _run повторит команду
    # без него (см. _ALLINTRA), а «Обработка» делает то же в ProcessWorker.
    aom_common = ["-usage", "allintra",
                  "-cpu-used", str(max(0, min(8, aspd))),
                  "-aom-params", "tune=iq",
                  "-tile-columns", "1", "-tile-rows", "1", "-row-mt", "1"]
    if has_alpha:
        if scale_vf:
            fc = (f"[0:v]format=yuva420p10le,split[c][a];"
                  f"[c]{scale_vf}[main];[a]alphaextract,{scale_vf}[alf]")
        else:
            fc = "[0:v]format=yuva420p10le,split[main][a];[a]alphaextract[alf]"
        return [FFMPEG, "-y", "-i", src, "-filter_complex", fc,
                "-map", "[main]", "-map", "[alf]", "-map_metadata", "-1",
                "-c:v", "libaom-av1", "-crf", str(crf_val)] + aom_common + \
               ["-still-picture", "1", "-threads", "0", tmp_out]
    cmd = [FFMPEG, "-y", "-i", src]
    if scale_vf:
        cmd += ["-vf", scale_vf]
    return cmd + ["-frames:v", "1", "-map_metadata", "-1", "-c:v", "libaom-av1",
                  "-crf", str(crf_val)] + aom_common + \
                 ["-pix_fmt", pix_fmt, "-threads", "0", tmp_out]


def downscale_side(orig_w, orig_h, baseline_kb, limit_kb) -> int:
    """Макс. сторона для первой попытки даунскейла, когда ни один CQ не влез.

    Оценка от известной точки (размер на CQ=63): считаем, что размер файла
    примерно пропорционален числу пикселей, берём нужную долю площади и
    переводим её в сторону (корень), с запасом 2% вниз. Клампим долю к 1.0
    и дополнительно требуем реального уменьшения (иначе следующая проба
    была бы точной копией предыдущей и проход терялся бы впустую)."""
    baseline_bytes = baseline_kb * 1024
    target_bytes = limit_kb * 1024
    orig_pixels = orig_w * orig_h
    approx_ratio = float(target_bytes) / float(baseline_bytes) if baseline_bytes > 0 else 0.5
    approx_ratio = max(0.01, min(1.0, approx_ratio))
    target_pixels = max(1, int(orig_pixels * approx_ratio * 0.98))
    scale_factor = (target_pixels / orig_pixels) ** 0.5
    new_max_side = max(1, int(max(orig_w, orig_h) * scale_factor))
    if new_max_side >= max(orig_w, orig_h):
        new_max_side = max(1, int(max(orig_w, orig_h) * 0.9))
    return new_max_side


def next_probe_cq(bad_cq, bad_size, good_cq, good_size, limit_kb) -> int:
    """Следующий CQ для пробы между «не влезло» (bad) и «влезло» (good).

    log(size) у AV1 примерно линеен по CQ, поэтому вилка сужается не слепым
    делением пополам, а интерполяцией по логарифмам размеров — так нужный CQ
    находится за 3-4 прохода вместо 6-8 (см. память
    avif-fit-passes-binary-search-depth)."""
    if bad_size == good_size:
        mid = (bad_cq + good_cq) // 2
    else:
        lt = math.log(max(1, limit_kb * _TARGET_BIAS))
        lo, hi = math.log(max(1, bad_size)), math.log(max(1, good_size))
        frac = max(0.0, min(1.0, (lo - lt) / (lo - hi)))
        mid = int(round(bad_cq + frac * (good_cq - bad_cq)))
    lo_cq, hi_cq = min(bad_cq, good_cq), max(bad_cq, good_cq)
    return max(lo_cq + 1, min(hi_cq - 1, mid))


# Кодирование идёт фоном к обычной работе за компьютером, поэтому процессы
# запускаются с низким приоритетом — тот же IDLE_PRIORITY_CLASS, что ставит
# «Обработка» при выборе «Низкий» (ProcessWorker._priority_creationflag).
_LOW_PRIORITY = (getattr(subprocess, "IDLE_PRIORITY_CLASS", 0)
                 if os.name == "nt" else 0)


_ALLINTRA = ["-usage", "allintra"]
# Знает ли местный ffmpeg про allintra: None — ещё не проверяли. Проверка идёт
# по факту первого неудачного кодирования, отдельного пробного запуска нет.
_allintra_ok: Optional[bool] = None


def strip_allintra(cmd) -> list:
    """Та же команда, но без `-usage allintra` — для сборок ffmpeg, которые
    этого значения не знают (значение появилось в libaom 3.2)."""
    for i in range(len(cmd) - 1):
        if cmd[i] == "-usage" and cmd[i + 1] == "allintra":
            return list(cmd[:i]) + list(cmd[i + 2:])
    return list(cmd)


_strip_allintra = strip_allintra          # прежнее внутреннее имя


def _run(cmd, should_stop=None) -> bool:
    """Одно кодирование. Если сборка ffmpeg не знает `-usage allintra`, команда
    повторяется без него и дальше он больше не подставляется."""
    global _allintra_ok
    if _allintra_ok is False:
        cmd = _strip_allintra(cmd)
    ok = _run_once(cmd, should_stop)
    if ok:
        if _allintra_ok is None and _ALLINTRA[0] in cmd:
            _allintra_ok = True
        return True
    if _allintra_ok is None and not (should_stop and should_stop()):
        plain = _strip_allintra(cmd)
        if plain != list(cmd) and _run_once(plain, should_stop):
            _allintra_ok = False
            return True
    return False


def _run_once(cmd, should_stop=None) -> bool:
    kw = ({"creationflags": CREATE_NO_WINDOW | _LOW_PRIORITY}
          if os.name == "nt" else {})
    if should_stop is None:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=600, **kw)
        except Exception:
            return False
        return proc.returncode == 0
    # С should_stop процесс ждём короткими шагами и убиваем по первому же
    # сигналу: иначе «Стоп» в генераторе паков ждал бы конца кодирования.
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, **kw)
    except Exception:
        return False
    deadline = time.monotonic() + 600
    while True:
        # Ждём именно wait(timeout=…), а не sleep: он возвращается В МОМЕНТ
        # выхода процесса, тогда как сон досыпал свой шаг до конца. На пачке
        # картинок это заметно — кодирование одной пробы идёт полсекунды, а
        # досыпалось в среднем по 75 мс (замер: 29 проб, 13,8 с против 12,9 с).
        try:
            proc.wait(timeout=0.1)
            return proc.returncode == 0
        except subprocess.TimeoutExpired:
            pass
        if should_stop() or time.monotonic() > deadline:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
            return False


def start_cq_guess(width: int, height: int, limit_kb: int) -> int:
    """С какого CQ начинать подбор, чтобы не тратить проход впустую.

    Первая проба всегда шла с CQ=0 — это самое медленное и самое «жирное»
    кодирование, а для обычного лимита в полтораста килобайт оно промахивается
    мимо цели на порядок, то есть проход уходит в никуда.

    Числа подобраны замерами на живых картинках Shikimori: постер 700×990 и
    кадр 1920×1080 укладываются в 150 КБ на CQ 20 и CQ 10 соответственно, а
    удвоение лимита стоит примерно пятнадцати ступеней CQ. Точность тут и не
    нужна — это лишь стартовая точка вилки, дальше её сужает интерполяция."""
    pixels = max(1, int(width) * int(height))
    limit = max(1, int(limit_kb))
    cq = (143.0 - 6.3 * math.log2(pixels)
          + 15.0 * math.log2(limit / 150.0)
          + 2.0)          # чуть в сторону «влезет» — такую пробу можно сохранить
    return int(max(CQ_BEST + 2, min(CQ_WORST - 2, round(cq))))


def fit_to_limit(src: str, out: str, limit_kb: int = 150, *, speed: int = 5,
                 passes: int = 4, chroma: str = "420",
                 start_cq: Optional[int] = None, max_side: int = 0,
                 should_stop=None, log=None) -> bool:
    """Кодирует src в AVIF ≤ limit_kb килобайт и кладёт результат в out.

    Та же стратегия, что в «Обработке» (ProcessWorker.process_avif): пробуем
    оба конца диапазона (CQ=0 — максимум качества, CQ=63 — минимум), затем
    сужаем вилку log-интерполяцией, а если даже CQ=63 не влезает — ужимаем
    разрешение по оценке от этой пробы. Возвращает True, если файл записан.

    Упрощения против «Обработки» (там это настройки пользователя): без альфы,
    без EXIF-поворота и без резервного WebP — сюда приходят уже готовые JPEG
    с Shikimori, а пак не должен зависеть от настроек вкладки «Обработка»."""
    tmp_files: list[str] = []
    best_tmp, best_size = None, -1
    w0, h0 = _dimensions(src)
    # Предварительный даунскейл (max_side): гнать 1200×1700 постер целиком, чтобы
    # потом ужать его до полутора сотен килобайт, — это лишние пиксели, а время
    # кодирования почти прямо пропорционально их числу.
    pre_vf = ""
    if max_side and w0 and h0 and max(w0, h0) > int(max_side):
        side = int(max_side)
        pre_vf = (f"scale=if(gt(iw\\,ih)\\,{side}\\,-2)"
                  f":if(gt(ih\\,iw)\\,{side}\\,-2)")
        k = float(side) / max(w0, h0)
        w0, h0 = max(1, int(w0 * k)), max(1, int(h0 * k))

    def _probe(cq, scale_vf=None):
        vf = scale_vf or pre_vf or None
        tmp = os.path.join(TEMP_DIR, f"avif_{uuid.uuid4().hex}_{cq}.avif")
        tmp_files.append(tmp)
        if not _run(avif_encode_cmd(src, tmp, cq, vf, False,
                                    avif_pix_fmt(False, chroma), speed),
                    should_stop):
            return None, 0
        if not os.path.exists(tmp):
            return None, 0
        return tmp, max(1, os.path.getsize(tmp) // 1024)

    def _keep(tmp, size):
        """Из влезших держим САМЫЙ КРУПНЫЙ — он же самый качественный."""
        nonlocal best_tmp, best_size
        if size > best_size:
            best_tmp, best_size = tmp, size

    try:
        budget = max(1, min(8, int(passes)))
        # Откуда начинать. По умолчанию — с CQ=0, как раньше (это самое
        # качественное кодирование, и если оно уже влезает в лимит, лучше не
        # найти). Со start_cq первая проба идёт сразу из середины: для тесных
        # лимитов CQ=0 промахивается на порядок, и проход тратится впустую.
        first = CQ_BEST if start_cq is None else int(
            max(CQ_BEST + 1, min(CQ_WORST - 1, start_cq)))
        tmp0, size0 = _probe(first)
        if tmp0 is None:
            return False
        used = 1
        size_worst = None
        if first == CQ_BEST and size0 <= limit_kb:
            _keep(tmp0, size0)              # лучше уже не сделать
        else:
            if size0 <= limit_kb:
                # Влезло с ходу: качество можно ещё поднять, опуская CQ. Нижний
                # конец вилки — CQ=0, его размер неизвестен, поэтому оцениваем
                # (на каждые ~20 ступеней CQ размер меняется примерно вчетверо).
                good_cq, good_size = first, size0
                _keep(tmp0, size0)
                bad_cq = CQ_BEST
                bad_size = max(limit_kb + 1, int(size0 * 4 ** (first / 20.0)))
            else:
                bad_cq, bad_size = first, size0
                good_cq, good_size = None, None
                if used < budget:
                    tmp63, size63 = _probe(CQ_WORST)
                    used += 1
                    if tmp63 is not None:
                        size_worst = size63
                        if size63 <= limit_kb:
                            good_cq, good_size = CQ_WORST, size63
                            _keep(tmp63, size63)
                        else:
                            bad_cq, bad_size = CQ_WORST, size63
            while (good_cq is not None and abs(good_cq - bad_cq) > 1
                   and used < budget):
                mid = next_probe_cq(bad_cq, bad_size, good_cq, good_size, limit_kb)
                tmp, size = _probe(mid)
                used += 1
                if tmp is None:
                    break
                if size <= limit_kb:
                    good_cq, good_size = mid, size
                    _keep(tmp, size)
                else:
                    bad_cq, bad_size = mid, size

        if best_tmp is None and size_worst is not None:
            # Даже минимальное качество не влезло — режем разрешение по оценке
            # от пробы CQ=63 (та же формула, что в «Обработке»).
            w, h = w0, h0
            if w and h:
                side = downscale_side(w, h, size_worst, limit_kb)
                for _ in range(5):
                    vf = (f"scale=if(gt(iw\\,ih)\\,{side}\\,-2)"
                          f":if(gt(ih\\,iw)\\,{side}\\,-2)")
                    tmp, size = _probe(CQ_WORST, scale_vf=vf)
                    if tmp is None:
                        break
                    if size <= limit_kb:
                        _keep(tmp, size)
                        break
                    side = max(1, int(side * 0.8))

        if best_tmp is None or not os.path.exists(best_tmp):
            return False
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        if os.path.exists(out):
            try:
                os.remove(out)
            except OSError:
                pass
        os.replace(best_tmp, out)
        if log:
            log(f"AVIF {os.path.basename(out)}: {best_size} КБ")
        return True
    finally:
        for tmp in tmp_files:
            if tmp != best_tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def _dimensions(path) -> tuple[int, int]:
    try:
        from config import Image
        if Image is not None:
            with Image.open(path) as im:
                return im.size
    except Exception:
        pass
    return 0, 0
