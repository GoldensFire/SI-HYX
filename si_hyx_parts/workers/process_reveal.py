# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Обработка: кадрирование и эффект проявления из Монтажа одним кодированием.

Режим «Перекодировать настройками «Обработки»» в Монтаже кладёт в элемент
очереди item['reveal'] = {'crop': <crop=…>, 'pixelize': (шаги, блок),
'effect': <ключ frame_reveal>, 'steps': N, 'dvd_media': <папка DVD>}.

Кадрирование и пикселизация — обычные фильтры ffmpeg и встают в цепочку
«Обработки» (montage_fx_vf). Остальные эффекты считаются по кадрам в Python,
поэтому видео приходит в кодировщик «Обработки» по трубе (RevealFeed,
reveal_pipe — та же, что у экспорта самого Монтажа):
декодер (рез, накладки, кадрирование, субтитры) → кадр через эффект → тот же
единственный кодировщик AV1 с настройками «Обработки». Промежуточного файла и
второго кодирования нет.

Картинка из Монтажа (item['still'] = {'fps': N}, длина — item['dur']) идёт той
же трубой всегда, с эффектом или без: декодер зацикливает её (-loop 1), кладёт
кадрирование, пикселизацию и накладки, а кодировщик «Обработки» получает
готовые кадры — как и у видео, одним кодированием.
"""
import threading

import reveal_pipe
from pixelize import pixelize_filter

import workers as _api


def burn_subs_filters(item, t0):
    """Фильтры вшивания субтитров из Монтажа (item['burn_subs']) или [].

    Отрезок вырезается быстрым ВХОДНЫМ pre-seek'ом, а он обнуляет тайминги в
    своей точке — время фильтрграфа идёт не от начала файла, а от t0 (см.
    _trim_seek_args). Фильтр же subtitles сопоставляет реплики со временем
    САМОГО файла субтитров, поэтому на время его работы возвращаем исходную
    шкалу и сразу возвращаем обратно; иначе текст уехал бы ровно на pre-seek."""
    burn = item.get('burn_subs') or {}
    if not burn.get('vf'):
        return []
    off = float(burn.get('src_in') or 0.0) - float(t0 or 0.0)
    if off > 0.001:
        return [f"setpts=PTS+{off:.6f}/TB", burn['vf'], f"setpts=PTS-{off:.6f}/TB"]
    return [burn['vf']]


def montage_fx_vf(item, t0):
    """(до субтитров, после субтитров) — фильтры Монтажа для цепочки
    «Обработки». Пикселизация считает окна в шкале фильтрграфа: клип в ней
    начинается с t0 (см. _trim_seek_args)."""
    fx = item.get('reveal') or {}
    before = [fx['crop']] if fx.get('crop') else []
    after = []
    pix = fx.get('pixelize')
    if pix:
        chain = pixelize_filter(item.get('dur') or 0.0, pix[0], pix[1], t0)
        if chain:
            after.append(chain)
    return before, after


def reveal_feed(worker, item, path):
    """RevealFeed для эффекта, который считается по кадрам (и для картинки
    из Монтажа — всегда), или None."""
    fx = item.get('reveal') or {}
    trim = item.get('trim')
    if item.get('still'):
        return RevealFeed(worker, item, path, None, fx)
    if not fx.get('effect') or not trim:
        return None
    return RevealFeed(worker, item, path, trim, fx)


class RevealFeed:
    """Труба «декодер → эффект → stdin кодировщика» для одного элемента."""

    def __init__(self, worker, item, path, trim, fx):
        self.path = path
        self.effect = fx.get('effect')
        self.steps = int(fx.get('steps') or 6)
        self.dvd_media = str(fx.get('dvd_media') or "")
        self.still = bool(item.get('still'))
        if self.still:
            self.fps = float(item['still'].get('fps') or 25)
            self.rate = f"{self.fps:g}"
            self.dur = max(0.0, float(item.get('dur') or 0.0))
            pre = ["-loop", "1", "-framerate", self.rate]
            post = ["-t", f"{self.dur:.6f}"]
            t0 = 0.0
        else:
            in_s, out_s = float(trim[0]), float(trim[1])
            self.dur = max(0.0, out_s - in_s)
            self.rate, self.fps = reveal_pipe.probe_rate(_api.FFPROBE, path, _api.CREATE_NO_WINDOW)
            pre, post, t0 = worker._trim_seek_args(in_s, out_s, 1.0)
        # Всё, что Монтаж кладёт на кадр ДО эффекта, считает декодер: так
        # эффект ложится поверх накладок и субтитров, как при обычной обрезке.
        # Пикселизация сюда попадает только у картинки (у видео без покадрового
        # эффекта трубы нет — её ставит montage_fx_vf в цепочку кодировщика).
        base = [fx['crop']] if fx.get('crop') else []
        timed = burn_subs_filters(item, t0)
        pix = fx.get('pixelize')
        if pix:
            chain = pixelize_filter(self.dur, pix[0], pix[1], t0)
            if chain:
                timed.append(chain)
        base += timed
        # Масштаб «Обработки» — уже здесь, до эффекта: иначе эффект считается
        # по кадрам исходника (картинка 7632×4288 — по 98 МБ на кадр, ролик
        # шёл 10–15 минут), а кодировщик всё равно сожмёт их до того же
        # размера. Его scale «не больше WxH» на готовом кадре ничего не меняет.
        # С обрезкой чёрных полос не трогаем: её рамка считается по исходнику.
        sv = (getattr(worker, 'settings', None) or {}).get('video', {})
        scale = (None if sv.get('crop_black')
                 else worker._scale_vf(sv.get('res', 'Исходное') or 'Исходное'))
        if scale:
            base.append(scale)
        # Картинка без фильтров, зависящих от времени (субтитры, пикселизация):
        # -loop 1 разжимал бы исходник (JPEG в десятки мегапикселей) на каждом
        # кадре заново. Разжимаем и сжимаем один раз, дальше кадр повторяет
        # фильтр loop; длину по-прежнему задаёт выходной -t.
        if self.still and not timed:
            pre = ["-framerate", self.rate]       # шкала кадра = 1/fps, а не 1/25
            base +=["loop=loop=-1:size=1:start=0", f"setpts=N/({self.rate}*TB)"]
        base.append(reveal_pipe.rgb_filter(path, _api.escape_filter_path))
        rendered = [tuple(o) for o in (item.get('overlays') or [])]
        fmt = item.get('overlay_format') or _api.overlay_chroma_format(_api.get_pix_fmt(path))
        vf = _api.overlay_filter_graph(",".join(base), rendered, pix_fmt=fmt)
        self.decode_cmd = ([_api.FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error"]
                           + pre + ["-i", path] + post
                           + ["-map", "0:V:0", "-vf", vf, "-an", "-sn", "-dn"]
                           + reveal_pipe.PPM_ARGS + ["-"])
        # Вход 0 — кадры с эффектом, вход 1 — звук того же отрезка (входной
        # seek режет звук точно, а выходной -ss срезал бы и кадры из трубы).
        # У картинки звука нет — только кадры.
        self.input_args = reveal_pipe.PPM_ARGS + ["-framerate", self.rate, "-i", "-"]
        if not self.still:
            self.input_args += ["-ss", f"{in_s:.6f}", "-t", f"{self.dur:.6f}", "-i", path]
        self.encode_vf = reveal_pipe.ENCODE_VF
        self.error = None
        self._dec = None
        self._thread = None
        self._stopped = False

    def start(self, stdin):
        """Запуск декодера и потока, который кормит stdin кодировщика."""
        kw = {'creationflags': _api.CREATE_NO_WINDOW} if _api.IS_WIN else {}
        self._dec = _api.subprocess.Popen(self.decode_cmd, stdout=_api.subprocess.PIPE,
                                          stderr=_api.subprocess.DEVNULL,
                                          stdin=_api.subprocess.DEVNULL, **kw)
        self._thread = threading.Thread(target=self._pump, args=(stdin,), daemon=True)
        self._thread.start()

    def _pump(self, stdin):
        from frame_reveal_video import VideoReveal
        total = max(1, round(self.dur * self.fps))
        reveal = (VideoReveal(self.effect, self.steps, total, self.fps, still=self.still,
                              dvd_media=self.dvd_media,
                              ffmpeg=_api.FFMPEG, ffprobe=_api.FFPROBE)
                  if self.effect else None)
        try:
            frames = reveal_pipe.pump(self._dec.stdout, stdin, reveal, lambda: self._stopped)
            if frames == 0 and not self._stopped:
                self.error = "декодер не отдал ни одного кадра"
        except (BrokenPipeError, OSError, ValueError):
            pass                       # кодировщик закрылся — причину скажет он
        except Exception as e:  # noqa: BLE001 — ошибка эффекта уходит в лог
            self.error = str(e)
        finally:
            if reveal is not None:
                reveal.close()

    def stop(self):
        self._stopped = True
        p = self._dec
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass

    def join(self):
        if self._thread is not None:
            self._thread.join()
        if self._dec is not None:
            try:
                self._dec.wait(timeout=30)
            except Exception:
                self.stop()
