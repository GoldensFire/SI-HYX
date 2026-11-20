# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: картинки поверх видео и размер клипа прямо в окне просмотра.

Картинка, которую открыли, бросили на видео или таймлайн или добавили «＋»,
когда в проекте уже есть видео, ложится поверх кадра у плейхеда (верхняя
видеодорожка, полкадра по центру). В плеере её не открывают — видео под ней
остаётся на месте.

Рамка (ClipFrameEditor холста плеера и FxPreviewView) — у выбранного на
таймлайне видеоклипа, который виден на плейхеде; клик по кадру выбирает
верхний клип под курсором. Уголки меняют размер (scale, у наложения с
box — box), тело — место (pos_x/pos_y). Рамка — в долях кадра проекта; живой
плеер показывает кадр одного клипа, поэтому там доли пересчитываются через
прямоугольник показанного клипа (_frame_view_rect).

Перенос в просмотре с эффектами — вживую (FxPreviewView.set_ghost): для
видеоклипов под плейхедом заранее рендерится кадр без клипа (фон). Ключ фона
— клип, время и проект без места и размера этого клипа, поэтому после
переноса фон тот же и следующий перенос снова сразу живой."""
import collections
import hashlib
import json

import montage_project as _mp

import edit_tab as _api

_IMAGE_SCALE = 0.5          # картинка поверх кадра — в полкадра, по центру
_POS_RANGE = (-1.0, 2.0)    # центр клипа может уйти за край кадра (как у ключевых кадров)
_GHOST_DELAY_MS = 200       # плейхед и проект успокоились — готовим фоны
_GHOST_CLIPS = 4            # столько клипов под плейхедом готовим заранее
_GHOST_CACHE = 8
_PLACE_KEYS = ("pos_x", "pos_y", "scale", "box")


class EditTabProjectFrameMixin:
    """Монтаж: картинки поверх видео и рамка размера клипа в просмотре."""

    # ── Картинки на таймлайн ─────────────────────────────────────────────────
    def _frame_images_over_video(self, paths):
        """Картинки из paths — поверх видео проекта; остальные пути (видео,
        звук, картинки в проект без видео) — список для прежнего пути."""
        if not self.project.has_video():
            return list(paths)
        images = [x for x in paths if _api.is_image_path(x) and _api.os.path.isfile(x)]
        if images:
            self.project_add_images(images)
        return [x for x in paths if x not in images]

    def project_add_images(self, paths):
        """Картинки — на верхнюю видеодорожку с плейхеда, одна за другой, без
        открытия в плеере. Возвращает добавленные клипы."""
        p = self.project
        start = float(self.project_timeline.playhead)
        dur = max(_mp.MIN_CLIP_S, float(getattr(self, "_still_duration", 5.0) or 5.0))
        items, bad = [], []
        for path in paths:
            img = _api.read_qimage(path)
            if img is None:
                bad.append(_api.os.path.basename(str(path)))
            else:
                items.append((str(path), img.width(), img.height()))
        if bad:
            _api.msgbox_warning(self, "Не удалось открыть",
                                "Файл не похож на картинку или формат не поддерживается:\n"
                                + "\n".join(bad))
        if not items:
            return []
        self._project_snapshot()
        track = self._frame_free_track(start, start + dur * len(items))
        added, t = [], start
        for path, w, h in items:
            clip = _mp.Clip(src=path, in_s=0.0, out_s=dur, track=track, start=t,
                            has_video=True, is_image=True, width=w, height=h,
                            fps=0.0, src_duration=dur, scale=_IMAGE_SCALE)
            p.append(clip)
            added.append(clip)
            t = clip.end
        self._project_changed()
        self.project_timeline.select([c.id for c in added], added[0].id)
        names = ", ".join(_api.os.path.basename(c.src) for c in added)
        self._proj_status(f"картинка поверх видео: {names} — тяните уголки рамки в "
                          "окне просмотра, чтобы поменять размер, или саму картинку")
        return added

    def _frame_free_track(self, t0, t1):
        """Верхняя видеодорожка, свободная на [t0, t1); нет такой — новая."""
        p = self.project
        for ti in p.tracks_of('video'):
            if ti == p.main_track:
                continue
            if all(c.end <= t0 + 1e-6 or c.start >= t1 - 1e-6 for c in p.clips_on(ti)):
                return ti
        return p.add_track('video')

    # ── Рамка в окне просмотра ───────────────────────────────────────────────
    def _frame_connect(self, view):
        """Сигналы рамки экрана просмотра (холст плеера, FxPreviewView)."""
        if not hasattr(view, "clipFrameEdited"):
            return
        view.clipFrameEdited.connect(lambda old, new, v=view: self._frame_edited(v, old, new))
        view.clipFramePicked.connect(lambda pt, v=view: self._frame_picked(v, pt))

    def _frame_clip_rect(self, c):
        """Где клип c в кадре проекта (доли кадра): прямоугольник scale × кадр
        (у наложения с box — box) с центром в pos, кадр клипа вписан в него
        как в сборке (fit — с полями, fill/crop — во весь)."""
        p = self.project
        W, H, _fps = p.output_format()
        W, H = max(2, W), max(2, H)
        if c.track != p.main_track and c.box:
            bw, bh = W * c.box[0], H * c.box[1]
        else:
            bw, bh = W * c.scale, H * c.scale
        cw, ch = float(c.width or bw), float(c.height or bh)
        if c.crop:
            x0, y0, x1, y1 = c.crop
            cw, ch = cw * max(1e-3, x1 - x0), ch * max(1e-3, y1 - y0)
        if (c.fit or p.settings.fit) == 'fit' and cw > 0 and ch > 0:
            k = min(bw / cw, bh / ch)
            bw, bh = cw * k, ch * k
        return _api.QRectF(c.pos_x - bw / W / 2.0, c.pos_y - bh / H / 2.0, bw / W, bh / H)

    def _frame_view_rect(self, view):
        """Какая часть кадра проекта (доли) показана на экране просмотра
        целиком: у просмотра с эффектами — весь кадр, у живого плеера — кадр
        клипа, который он сейчас показывает."""
        if view is self._fx_view:
            return _api.QRectF(0.0, 0.0, 1.0, 1.0)
        c = self.project.clip(self._proj_cur_id)
        if c is None or not c.has_video:
            return _api.QRectF(0.0, 0.0, 1.0, 1.0)
        r = self._frame_clip_rect(c)
        return r if r.width() > 1e-6 and r.height() > 1e-6 else _api.QRectF(0.0, 0.0, 1.0, 1.0)

    @staticmethod
    def _frame_to_view(r, area):
        return _api.QRectF((r.x() - area.x()) / area.width(), (r.y() - area.y()) / area.height(),
                           r.width() / area.width(), r.height() / area.height())

    @staticmethod
    def _frame_from_view(r, area):
        return _api.QRectF(area.x() + r.x() * area.width(), area.y() + r.y() * area.height(),
                           r.width() * area.width(), r.height() * area.height())

    def _frame_target(self):
        """Клип под рамкой: выбранный видеоклип, видимый на плейхеде."""
        tl = getattr(self, "project_timeline", None)
        if tl is None or getattr(self, "_fs_window", None) is not None:
            return None
        c = self.project.clip(tl.selected)
        if c is None or not c.has_video or not self.project.tracks[c.track].enabled:
            return None
        if any(k in c.keyframes for k in ("scale", "pos_x", "pos_y")):
            return None                  # размер и место ведут ключевые кадры
        t = float(tl.playhead)
        if not (c.start - 1e-6 <= t < c.end):
            return None
        return c

    def _frame_views(self):
        views = []
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, _api.VideoCanvas):
            views.append(vw)
        if self._fx_view is not None:
            views.append(self._fx_view)
        return views

    def _frame_refresh(self):
        """Рамка на экранах просмотра — по выбранному клипу и плейхеду."""
        c = self._frame_target()
        for view in self._frame_views():
            if c is None:
                view.set_clip_frame(None)
                continue
            area = self._frame_view_rect(view)
            view.set_clip_frame(self._frame_to_view(self._frame_clip_rect(c), area))
        self._frame_ghost_push(c)

    # ── Живой перенос: фон без клипа ─────────────────────────────────────────
    def _frame_ghost_invalidate(self):
        """Проект изменился: ключи фонов — заново (из _fx_project_changed)."""
        self._frame_ghost_rev = getattr(self, "_frame_ghost_rev", 0) + 1
        self._frame_ghost_schedule()

    def _frame_ghost_schedule(self, restart=True):
        timer = getattr(self, "_frame_ghost_timer", None)
        if timer is None:
            timer = _api.QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(_GHOST_DELAY_MS)
            timer.timeout.connect(self._frame_ghost_prepare)
            self._frame_ghost_timer = timer
        if restart or not timer.isActive():
            timer.start()

    def _frame_ghost_state(self):
        return (round(float(self.project_timeline.playhead), 4),
                getattr(self, "_frame_ghost_rev", 0))

    def _frame_ghost_ready(self):
        return (self._fx_mode and not self._fx_playing and self._fx is not None
                and self._fx_view is not None and self._fx_view.has_image())

    def _frame_ghost_key(self, base, c, t):
        """Ключ фона клипа c: клип, время и проект без места и размера c."""
        d = dict(base)
        d["clips"] = [{k: v for k, v in cd.items() if k not in _PLACE_KEYS}
                      if cd.get("id") == c.id else cd for cd in base.get("clips", [])]
        blob = json.dumps(d, sort_keys=True, ensure_ascii=False, default=str)
        return (c.id, round(float(t), 4), hashlib.sha1(blob.encode("utf-8")).hexdigest())

    def _frame_ghost_project(self, cid):
        """Копия проекта, где клипа cid не видно."""
        q = self.project.copy()
        c = q.clip(cid)
        if c is not None:
            if c.track != q.main_track:
                c.opacity = 0.0              # наложения без непрозрачности граф пропускает
            else:
                c.pos_x = c.pos_y = 10.0     # клип основной дорожки — за край кадра
        return q

    def _frame_ghost_prepare(self):
        """Фоны клипов под плейхедом — заранее, чтобы перенос сразу был живым."""
        if not self._frame_ghost_ready():
            return
        p = self.project
        t = float(self.project_timeline.playhead)
        cands = []
        for ti in reversed(p.tracks_of('video')):
            if not p.tracks[ti].enabled:
                continue
            c = p.clip_at(ti, t)
            if (c is not None and c.has_video
                    and not any(k in c.keyframes for k in ("scale", "pos_x", "pos_y"))):
                cands.append(c)
        target = self._frame_target()
        if target is not None:
            # Выбранный — первым и всегда (иначе push ждал бы его фон вечно).
            cands = [target] + [c for c in cands if c.id != target.id]
        cands = cands[:_GHOST_CLIPS]
        cache = self._frame_ghost_cache()
        base = p.to_dict()
        keys, jobs = {}, []
        for c in cands:
            key = self._frame_ghost_key(base, c, t)
            keys[c.id] = key
            if key not in cache:
                jobs.append((key, self._frame_ghost_project(c.id), t))
        self._frame_ghost_keys = (self._frame_ghost_state(), keys)
        if jobs:
            self._fx.aside(jobs)
        self._frame_ghost_push(target)

    def _frame_ghost_cache(self):
        """Готовые фоны: ключ → QImage (последние _GHOST_CACHE)."""
        cache = getattr(self, "_frame_ghost_bgs", None)
        if cache is None:
            cache = self._frame_ghost_bgs = collections.OrderedDict()
        return cache

    def _frame_ghost_on_ready(self, key, img):
        cache = self._frame_ghost_cache()
        cache[key] = img
        cache.move_to_end(key)
        while len(cache) > _GHOST_CACHE:
            cache.popitem(last=False)
        self._frame_ghost_push(self._frame_target())

    def _frame_ghost_opaque(self, c):
        """Клип закрывает всю свою рамку (тогда внутри рамки слой — целиком)."""
        if c.opacity < 0.999 or c.blend or c.mask or c.matte or c.effects:
            return False
        if not c.is_image:
            return True
        alpha = getattr(self, "_frame_alpha_cache", None)
        if alpha is None:
            alpha = self._frame_alpha_cache = {}
        if c.src not in alpha:
            img = _api.read_qimage(c.src)
            alpha[c.src] = img is not None and img.hasAlphaChannel()
        return not alpha[c.src]

    def _frame_ghost_pad(self, c, r):
        """Рамка клипа r с запасом на обводку и тень (доли кадра)."""
        m = 0.004
        if c.stroke:
            m += c.stroke["width"] * (3.0 if c.stroke.get("style") == "torn" else 2.2)
        if c.shadow:
            m += c.shadow["size"] * 3.0 + max(abs(c.shadow["x"]), abs(c.shadow["y"]))
        W, H, _fps = self.project.output_format()
        mx = m * max(2, H) / max(2, W)
        return r.adjusted(-mx, -m, mx, m)

    def _frame_ghost_push(self, c):
        """Окну просмотра с эффектами — фон под клипом c (или None)."""
        view = getattr(self, "_fx_view", None)
        if view is None:
            return
        state, keys = getattr(self, "_frame_ghost_keys", (None, {}))
        if c is None or not self._frame_ghost_ready():
            view.set_ghost(None)
            return
        if state != self._frame_ghost_state() or c.id not in keys:
            # Плейхед или проект сдвинулись: фон ещё не готов — перенос
            # пока поверх старого кадра, фон — после паузы.
            self._frame_ghost_schedule(restart=False)
            r = self._frame_clip_rect(c)
            view.set_ghost({'clip': r, 'pad': r, 'bg': None, 'opaque': True})
            return
        cache = self._frame_ghost_cache()
        r = self._frame_clip_rect(c)
        view.set_ghost({'clip': r, 'pad': self._frame_ghost_pad(c, r),
                        'bg': cache.get(keys[c.id]), 'opaque': self._frame_ghost_opaque(c)})

    def _frame_picked(self, view, pt):
        """Клик по кадру мимо рамки: выбрать верхний видимый клип под
        курсором (мимо всех — снять выделение)."""
        if getattr(self, "_fs_window", None) is not None:
            return                      # в полном экране клик выделение не трогает
        area = self._frame_view_rect(view)
        x = area.x() + pt.x() * area.width()
        y = area.y() + pt.y() * area.height()
        p = self.project
        t = float(self.project_timeline.playhead)
        hit = None
        for ti in reversed(p.tracks_of('video')):
            if not p.tracks[ti].enabled:
                continue
            c = p.clip_at(ti, t)
            if c is not None and c.has_video and self._frame_clip_rect(c).contains(x, y):
                hit = c
                break
        tl = self.project_timeline
        if hit is None:
            if tl.selected:
                tl.select([])
        elif hit.id != tl.selected:
            tl.select([hit.id], hit.id)
        self._frame_refresh()

    def _frame_edited(self, view, old, new):
        """Рамку потянули мышью: размер и место клипа — по ней."""
        c = self._frame_target()
        if c is None or old.width() <= 1e-9:
            self._frame_refresh()
            return
        area = self._frame_view_rect(view)
        old_p, new_p = self._frame_from_view(old, area), self._frame_from_view(new, area)
        ratio = new_p.width() / max(1e-9, old_p.width())
        self._project_snapshot()
        if c.track != self.project.main_track and c.box:
            c.box = _mp.sanitize_box([c.box[0] * ratio, c.box[1] * ratio])
        else:
            c.scale = max(_mp.MIN_SCALE, min(_mp.MAX_SCALE, c.scale * ratio))
        lo, hi = _POS_RANGE
        c.pos_x = round(max(lo, min(hi, c.pos_x + new_p.center().x() - old_p.center().x())), 6)
        c.pos_y = round(max(lo, min(hi, c.pos_y + new_p.center().y() - old_p.center().y())), 6)
        if abs(c.scale - 1.0) < 0.005 and abs(c.pos_x - 0.5) < 0.002 and abs(c.pos_y - 0.5) < 0.002:
            # Почти на месте во весь кадр — ровно как в исходнике.
            c.scale, c.pos_x, c.pos_y = 1.0, 0.5, 0.5
        self._project_changed()
