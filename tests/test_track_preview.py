# -*- coding: utf-8 -*-
"""Предпросмотр привязки к объекту и гашение дрожания накладки.

Проверяем то, что реально ломается при правках:
  • BoxSmoother — давит шум на стоящем объекте, но не «залипает» на движущемся;
  • limit_box_size — не даёт рамке раздуться (из-за этого трекер терял цель, а
    привязанный текст скакал по экрану);
  • track_box_at — одна и та же рамка в предпросмотре и в рендере;
  • VideoCanvas рисует накладку там же, где её нарисует ffmpeg-воркер.
"""
import numpy as np
import pytest

dt = pytest.importorskip("dyhit_tracker")
workers = pytest.importorskip("edit_tab_workers")


# ── сглаживание ──────────────────────────────────────────────────────────────
def _noisy_run(strength, moving=False, n=80, sigma=2.0, seed=0):
    rng = np.random.default_rng(seed)
    sm = dt.BoxSmoother(strength, fps=25.0)
    sm.reset([100.0, 100.0, 50.0, 50.0])
    out = []
    for i in range(n):
        x = 100.0 + (i * 4.0 if moving else 0.0)
        out.append(sm([x + rng.normal(0, sigma), 100 + rng.normal(0, sigma),
                       50 * (1 + rng.normal(0, 0.03)),
                       50 * (1 + rng.normal(0, 0.03))]))
    return np.array(out)


def test_smoother_off_returns_box_unchanged():
    sm = dt.BoxSmoother(0.0, fps=25.0)
    assert sm([1.5, 2.5, 3.5, 4.5]) == [1.5, 2.5, 3.5, 4.5]
    assert not sm.enabled


def test_smoother_kills_jitter_on_still_object():
    raw_sigma = 2.0
    got = _noisy_run(1.0)[10:]
    # Дрожание должно упасть в разы, а размер — замереть совсем (именно шум w/h
    # дёргает якоря «над/под областью» и масштаб накладки).
    assert got[:, 0].std() < raw_sigma / 4
    assert got[:, 1].std() < raw_sigma / 4
    assert got[:, 2].std() < 0.2


def test_smoother_freezes_completely_on_tiny_noise():
    """Объект стоит, трекер шумит на доли пикселя — накладка обязана СТОЯТЬ, а
    не ползать (на это жаловались в первую очередь)."""
    got = _noisy_run(1.0, sigma=0.3)[5:]
    assert got[:, 0].std() == pytest.approx(0.0, abs=1e-9)
    assert got[:, 1].std() == pytest.approx(0.0, abs=1e-9)


def test_smoother_leaves_deadband_without_a_jump():
    """Выход из мёртвой зоны — плавный: рамку сдвигаем на превышение порога, а
    не скачком на всю его ширину."""
    sm = dt.BoxSmoother(1.0, fps=25.0)
    sm.reset([100.0, 100.0, 50.0, 50.0])
    for _ in range(40):
        prev = sm([100.0, 100.0, 50.0, 50.0])
    steps = []
    for i in range(1, 40):
        cur = sm([100.0 + i * 3.0, 100.0, 50.0, 50.0])
        steps.append(cur[0] - prev[0])
        prev = cur
    assert max(steps) < 3.5          # ни одного «щелчка» больше самого движения


def test_smoother_keeps_up_with_movement():
    # 4 px/кадр: накладка обязана идти следом, а не отставать на полкадра пути.
    got = _noisy_run(1.0, moving=True)
    truth = 100.0 + np.arange(len(got)) * 4.0
    lag = (truth - got[:, 0])[-20:].mean()
    assert 0 < lag < 6.0


def test_smoother_first_box_is_exact():
    sm = dt.BoxSmoother(1.0, fps=30.0)
    assert sm([10, 20, 30, 40]) == [10, 20, 30, 40]


# ── ограничитель размера ─────────────────────────────────────────────────────
def test_limit_box_size_caps_growth_rate_and_keeps_center():
    prev = [100.0, 100.0, 50.0, 50.0]
    out = dt.limit_box_size([80, 80, 200, 200], prev, prev)
    assert out[2] == pytest.approx(50 * (1 + dt.SIZE_RATE))
    assert out[0] + out[2] / 2 == pytest.approx(180)      # центр — от предсказания
    assert out[1] + out[3] / 2 == pytest.approx(180)


def test_limit_box_size_stops_runaway():
    """Рамка не может уползти за SIZE_MAX_K, сколько бы кадров ни просили расти:
    без этого поисковое окно (×4 от рамки) раздувалось на весь кадр и цель
    терялась насовсем."""
    init = [0.0, 0.0, 50.0, 50.0]
    box = list(init)
    for _ in range(200):
        box = dt.limit_box_size([box[0], box[1], box[2] * 2, box[3] * 2],
                                box, init)
    assert box[2] == pytest.approx(50 * dt.SIZE_MAX_K)
    box = list(init)
    for _ in range(200):
        box = dt.limit_box_size([box[0], box[1], box[2] * 0.5, box[3] * 0.5],
                                box, init)
    assert box[2] == pytest.approx(50 * dt.SIZE_MIN_K)


# ── траектория ───────────────────────────────────────────────────────────────
def test_track_box_at_maps_time_to_frame():
    boxes = [[float(i), 0.0, 10.0, 10.0] for i in range(50)]
    assert workers.track_box_at(boxes, 2.0, 2.0, 25.0)[0] == 0.0
    assert workers.track_box_at(boxes, 2.4, 2.0, 25.0)[0] == 10.0
    # За краями отрезка — крайние рамки, а не исключение.
    assert workers.track_box_at(boxes, 0.0, 2.0, 25.0)[0] == 0.0
    assert workers.track_box_at(boxes, 99.0, 2.0, 25.0)[0] == 49.0
    assert workers.track_box_at([], 1.0, 0.0, 25.0) is None


def test_overlay_worker_accepts_trim_range():
    """«Обрезать» с накладкой отдаёт воркеру выделенный отрезок; без него —
    файл целиком (тогда время кадра считается от нуля)."""
    ovl = np.zeros((4, 4, 4), np.uint8)
    w = workers.TrackOverlayWorker("a.mp4", "b.mp4", [], False, 25.0,
                                   (640, 360), 60.0, [0, 0, 10, 10],
                                   0.0, 60.0, ovl, boxes=[[0, 0, 10, 10]],
                                   trim_in=12.0, trim_out=18.0)
    assert w._trim_in == 12.0 and w._trim_out == 18.0
    # Без обрезки время кадра считается от нуля.
    w2 = workers.TrackOverlayWorker("a.mp4", "b.mp4", [], False, 25.0,
                                    (640, 360), 60.0, [0, 0, 10, 10],
                                    0.0, 60.0, ovl)
    assert w2._trim_in == 0.0 and w2._trim_out == float('inf')


def test_track_path_worker_downscales_but_keeps_source_coords():
    w = workers.TrackPathWorker("x.mp4", 30.0, (1920, 1080), [10, 10, 50, 50],
                                0.0, 1.0)
    k, tw, th = w._scale()
    assert tw <= w.TRACK_MAX_SIDE and th <= w.TRACK_MAX_SIDE
    assert tw % 2 == 0 and th % 2 == 0
    assert k == pytest.approx(tw / 1920)
    # Маленькое видео не трогаем вовсе.
    small = workers.TrackPathWorker("x.mp4", 30.0, (640, 360), [1, 1, 5, 5],
                                    0.0, 1.0)
    assert small._scale() == (1.0, 640, 360)


# ── отрисовка предпросмотра ──────────────────────────────────────────────────
@pytest.fixture
def canvas(qapp):
    from PyQt6.QtGui import QImage
    widgets = pytest.importorskip("edit_tab_widgets")
    c = widgets.VideoCanvas()
    c.resize(640, 360)
    frame = QImage(640, 360, QImage.Format.Format_RGB32)
    frame.fill(0)
    c._frame_img = frame              # кадр «от плеера» — без реального плеера
    yield c
    c.deleteLater()


def _preview_spec(qimg, **kw):
    spec = {"overlay": qimg, "boxes": [[100.0, 100.0, 60.0, 60.0]],
            "src_w": 640, "src_h": 360, "fps": 25.0,
            "start_s": 0.0, "end_s": 10.0, "anchor": "top", "off": (0, 0),
            "scale_with_box": False}
    spec.update(kw)
    return spec


def test_canvas_preview_puts_overlay_where_worker_would(canvas):
    from PyQt6.QtGui import QImage
    ovl = QImage(40, 20, QImage.Format.Format_ARGB32)
    ovl.fill(0xFFFF0000)
    canvas.set_track_preview(_preview_spec(ovl))
    assert canvas.has_track_preview()
    rect, brect = canvas._track_overlay_rect(canvas.video_rect())
    # Холст ровно 640×360 — координаты кадра и экрана совпадают один к одному.
    x, y = workers.overlay_top_left([100, 100, 60, 60], 40, 20, "top")
    assert rect.left() == pytest.approx(x)
    assert rect.top() == pytest.approx(y)
    assert (brect.left(), brect.top()) == pytest.approx((100, 100))


def test_canvas_preview_scales_to_widget(canvas):
    """Рамки посчитаны в пикселях ИСХОДНИКА, а холст показывает кадр вписанным
    (и часто это ещё и прокси меньшего разрешения) — накладка обязана
    пересчитываться в экранные координаты, иначе уедет от объекта."""
    from PyQt6.QtGui import QImage
    ovl = QImage(40, 20, QImage.Format.Format_ARGB32)
    ovl.fill(0xFFFF0000)
    # Кадр от плеера — прокси 320×180, а холст вдвое меньше исходника.
    canvas._frame_img = QImage(320, 180, QImage.Format.Format_RGB32)
    canvas.resize(320, 180)
    canvas.set_track_preview(_preview_spec(ovl, src_w=640, src_h=360))
    vr = canvas.video_rect()
    assert (vr.width(), vr.height()) == (320, 180)
    rect, brect = canvas._track_overlay_rect(vr)
    x, y = workers.overlay_top_left([100, 100, 60, 60], 40, 20, "top")
    assert rect.left() == pytest.approx(x / 2, abs=0.5)
    assert rect.top() == pytest.approx(y / 2, abs=0.5)
    assert rect.width() == pytest.approx(20, abs=0.5)
    assert (brect.left(), brect.top()) == pytest.approx((50, 50))


def test_canvas_preview_hidden_outside_segment(canvas):
    from PyQt6.QtGui import QImage
    ovl = QImage(10, 10, QImage.Format.Format_ARGB32)
    ovl.fill(0xFFFF0000)
    canvas.set_track_preview(_preview_spec(ovl, start_s=2.0, end_s=4.0))
    canvas.set_track_time(1.0)
    assert canvas._track_overlay_rect(canvas.video_rect())[0] is None
    canvas.set_track_time(3.0)
    assert canvas._track_overlay_rect(canvas.video_rect())[0] is not None
    canvas.set_track_time(9.0)
    assert canvas._track_overlay_rect(canvas.video_rect())[0] is None


def test_canvas_preview_cleared(canvas):
    from PyQt6.QtGui import QImage
    ovl = QImage(10, 10, QImage.Format.Format_ARGB32)
    ovl.fill(0xFFFF0000)
    canvas.set_track_preview(_preview_spec(ovl))
    canvas.set_track_preview(None)
    assert not canvas.has_track_preview()
    assert canvas._track_overlay_rect(canvas.video_rect())[0] is None
