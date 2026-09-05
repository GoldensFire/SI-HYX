# -*- coding: utf-8 -*-
"""Отслеживание объекта (dyhit_tracker) и наложение накладки на кадр.

Сеть здесь не нужна: инференс DyHiT подменяется заглушкой-сессией, а проверяется
ровно то, что легко сломать при правках, — геометрия кропа, обратный пересчёт
рамки в координаты кадра, нормализация входа, «динамический» гейт по score,
сглаживание и позиционирование/смешивание накладки.
"""
import numpy as np
import pytest

import dyhit_tracker as dt
from edit_tab_workers import blend_bgra, overlay_top_left


# ── sample_target / clip_box / map_box_back ──────────────────────────────────

def test_sample_target_size_and_factor():
    im = np.zeros((480, 640, 3), np.uint8)
    patch, rf = dt.sample_target(im, [300, 200, 40, 40], 4.0, 256)
    assert patch.shape == (256, 256, 3)
    # Сторона кропа = 4 × √(40·40) = 160 → 256/160 = 1.6
    assert rf == pytest.approx(256 / 160)


def test_sample_target_pads_outside_frame():
    """Рамка у самого края: кроп добивается чёрным, а не «липнет» внутрь кадра."""
    im = np.full((100, 100, 3), 255, np.uint8)
    patch, _ = dt.sample_target(im, [0, 0, 20, 20], 4.0, 128)
    assert patch.shape == (128, 128, 3)
    assert patch[:8, :8].max() == 0          # левый верхний угол — паддинг
    assert patch[-8:, -8:].min() == 255      # правый нижний — сам кадр


def test_clip_box_keeps_box_inside_frame():
    assert dt.clip_box([-30, -30, 10, 10], 100, 200, margin=10) == [0.0, 0.0, 10.0, 10.0]
    x, y, w, h = dt.clip_box([190, 90, 50, 50], 100, 200, margin=10)
    assert x + w <= 200 and y + h <= 100


def test_map_box_back_is_inverse_of_centered_prediction():
    """Предсказание «цель ровно в центре поисковой области» не должно двигать рамку."""
    prev = [300.0, 200.0, 40.0, 40.0]
    rf = 256 / 160
    half = 0.5 * 256 / rf
    box = dt.map_box_back((half, half, 40.0, 40.0), prev, 256, rf)
    assert box[0] == pytest.approx(prev[0])
    assert box[1] == pytest.approx(prev[1])


def test_preprocess_patch_is_rgb_and_normalized():
    patch = np.zeros((4, 4, 3), np.uint8)
    patch[:, :, 2] = 255                     # чистый красный в BGR
    out = dt.preprocess_patch(patch)
    assert out.shape == (1, 3, 4, 4) and out.dtype == np.float32
    # Канал 0 (R) — единица после /255, каналы G/B — нули (значит BGR→RGB сделан).
    assert out[0, 0].mean() == pytest.approx((1.0 - 0.485) / 0.229, rel=1e-4)
    assert out[0, 2].mean() == pytest.approx((0.0 - 0.406) / 0.225, rel=1e-4)


def test_ema_smoothing():
    assert dt._ema(None, [1, 2, 3, 4], 0.5) == [1, 2, 3, 4]
    assert dt._ema([0, 0, 0, 0], [10, 10, 10, 10], 0.0) == [10, 10, 10, 10]
    assert dt._ema([0, 0, 0, 0], [10, 10, 10, 10], 0.5) == [5, 5, 5, 5]


# ── DyHiTTracker поверх заглушки onnxruntime-сессии ──────────────────────────

class _FakeSession:
    """Сессия, отдающая заранее заданный (cx, cy, w, h) в долях поисковой области."""

    def __init__(self, pred=(0.5, 0.5, 0.25, 0.25), score_map=None):
        self.pred = pred
        self.score_map = score_map
        self.calls = []

    def run(self, _outputs, feeds):
        self.calls.append(feeds)
        boxes = np.array([[list(self.pred)]], np.float32)
        return [boxes] if self.score_map is None else [boxes, self.score_map]


def _tracker_with(session, **kw):
    trk = dt.DyHiTTracker(model_path="(заглушка)", **kw)
    trk._session = session                 # _ensure_session вернёт её как есть
    trk._active_provider = "CPUExecutionProvider"
    trk._in_search, trk._in_template = "search", "template"
    return trk


def test_tracker_center_prediction_keeps_box():
    frame = np.zeros((480, 640, 3), np.uint8)
    trk = _tracker_with(_FakeSession(pred=(0.5, 0.5, 40 / 160, 40 / 160)))
    trk.init(frame, (300, 200, 40, 40))
    box, score = trk.update(frame)
    assert score is None
    assert box[0] == pytest.approx(300, abs=1.0)
    assert box[1] == pytest.approx(200, abs=1.0)
    assert box[2] == pytest.approx(40, abs=1.0)
    # На вход ушли оба тензора нужных размеров.
    feeds = trk._session.calls[-1]
    assert feeds["search"].shape == (1, 3, 256, 256)
    assert feeds["template"].shape == (1, 3, 128, 128)


def test_tracker_offset_prediction_moves_box_right():
    frame = np.zeros((480, 640, 3), np.uint8)
    # Цель на 75% ширины поисковой области → рамка уезжает вправо-вниз.
    trk = _tracker_with(_FakeSession(pred=(0.75, 0.5, 40 / 160, 40 / 160)))
    trk.init(frame, (300, 200, 40, 40))
    box, _ = trk.update(frame)
    # Сдвиг = 0.25 × сторона кропа (160 px).
    assert box[0] == pytest.approx(300 + 40, abs=1.0)
    assert box[1] == pytest.approx(200, abs=1.0)


def test_route_score_gate_dampens_jump_on_hard_frame():
    """Если карта роутера просела ниже threshold×score первого кадра, рамка
    сдвигается лишь наполовину (логика «сложного кадра» из DyHiT)."""
    frame = np.zeros((480, 640, 3), np.uint8)
    sess = _FakeSession(pred=(0.75, 0.5, 40 / 160, 40 / 160),
                        score_map=np.array([0.9, 0.9], np.float32))
    trk = _tracker_with(sess, threshold=0.75)
    trk.init(frame, (300, 200, 40, 40))
    box1, score1 = trk.update(frame)
    assert score1 == pytest.approx(0.9)
    full_step = box1[0] - 300

    sess.score_map = np.array([0.61, 0.61], np.float32)   # «сложный» кадр
    box2, score2 = trk.update(frame)
    assert score2 == pytest.approx(0.61)
    assert (box2[0] - box1[0]) == pytest.approx(full_step / 2, abs=1.0)


def test_tracker_requires_init():
    trk = _tracker_with(_FakeSession())
    with pytest.raises(RuntimeError):
        trk.update(np.zeros((10, 10, 3), np.uint8))


class _FakeInput:
    def __init__(self, name, shape):
        self.name, self.shape = name, shape


class _FakeIOSession:
    def __init__(self, inputs):
        self._inputs = inputs

    def get_inputs(self):
        return self._inputs


def test_read_io_takes_sizes_from_graph():
    """Размеры входов берём из самого графа — экспорт HiT-Tiny/Small/Base и
    DyHiT-route1 отличаются размерами, а код должен работать с любым."""
    trk = dt.DyHiTTracker(model_path="(заглушка)")
    trk._read_io(_FakeIOSession([_FakeInput("search", [1, 3, 224, 224]),
                                 _FakeInput("template", [1, 3, 112, 112])]))
    assert (trk.search_size, trk.template_size) == (224, 112)
    assert (trk._in_search, trk._in_template) == ("search", "template")


def test_read_io_detects_roles_by_size_when_names_differ():
    trk = dt.DyHiTTracker(model_path="(заглушка)")
    trk._read_io(_FakeIOSession([_FakeInput("z", [1, 3, 128, 128]),
                                 _FakeInput("x", [1, 3, 256, 256])]))
    assert trk._in_search == "x" and trk._in_template == "z"


def test_read_io_falls_back_on_dynamic_shapes():
    trk = dt.DyHiTTracker(model_path="(заглушка)")
    trk._read_io(_FakeIOSession([_FakeInput("search", [1, 3, "h", "w"]),
                                 _FakeInput("template", [1, 3, "h", "w"])]))
    assert (trk.search_size, trk.template_size) == (dt.SEARCH_SIZE, dt.TEMPLATE_SIZE)


def test_read_io_rejects_single_input_model():
    trk = dt.DyHiTTracker(model_path="(заглушка)")
    with pytest.raises(RuntimeError):
        trk._read_io(_FakeIOSession([_FakeInput("search", [1, 3, 256, 256])]))


def test_route_score_ignores_missing_second_output():
    trk = _tracker_with(_FakeSession())
    assert trk._route_score([np.zeros((1, 1, 4), np.float32)]) is None


# ── Поиск модели и выбор движка ──────────────────────────────────────────────

def test_find_model_path_none_when_models_dir_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(dt, "_models_dirs", lambda: [str(tmp_path)])
    assert dt.find_model_path() is None
    assert dt.dyhit_available() is False


def test_find_model_path_accepts_epoch_named_export(tmp_path, monkeypatch):
    (tmp_path / "DyHiT_ep0060.onnx").write_bytes(b"")
    monkeypatch.setattr(dt, "_models_dirs", lambda: [str(tmp_path)])
    assert dt.find_model_path().endswith("DyHiT_ep0060.onnx")


def test_create_tracker_dyhit_requires_model(tmp_path, monkeypatch):
    monkeypatch.setattr(dt, "_models_dirs", lambda: [str(tmp_path)])
    with pytest.raises(RuntimeError):
        dt.create_tracker(prefer="dyhit")
    # 'auto' молча откатывается на запасной трекер OpenCV.
    if dt.opencv_tracker_available():
        assert isinstance(dt.create_tracker(prefer="auto"), dt.OpenCVTracker)


@pytest.mark.skipif(not dt.opencv_tracker_available(),
                    reason="в сборке OpenCV нет трекеров")
def test_opencv_fallback_tracks_moving_square():
    """Запасной трекер реально ведёт объект: квадрат едет вправо на 4 px/кадр."""
    trk = dt.OpenCVTracker(smooth=0.0)
    import cv2
    rng = np.random.default_rng(7)

    def _frame(x):
        f = rng.integers(0, 60, (120, 320, 3)).astype(np.uint8)
        cv2.rectangle(f, (x, 40), (x + 30, 70), (40, 200, 250), -1)
        return f

    trk.init(_frame(20), (20, 40, 30, 30))
    box = None
    for i in range(1, 11):
        box, _ = trk.update(_frame(20 + 4 * i))
    assert box[0] == pytest.approx(60, abs=6)


# ── Геометрия и смешивание накладки ─────────────────────────────────────────

@pytest.mark.parametrize("anchor,expected", [
    ("center", (105.0, 35.0)),
    ("top", (105.0, 10.0)),
    ("bottom", (105.0, 60.0)),
    ("left", (90.0, 35.0)),
    ("right", (120.0, 35.0)),
])
def test_overlay_top_left_anchors(anchor, expected):
    # рамка (100, 20, 20, 40) → центр (110, 40); накладка 10×10
    assert overlay_top_left([100, 20, 20, 40], 10, 10, anchor) == expected


def test_overlay_top_left_offsets():
    assert overlay_top_left([100, 20, 20, 40], 10, 10, "center", 5, -7) == (110.0, 28.0)


def test_blend_bgra_respects_alpha():
    frame = np.zeros((10, 10, 3), np.uint8)
    ovl = np.zeros((4, 4, 4), np.uint8)
    ovl[:, :, 2] = 200          # красный
    ovl[:2, :, 3] = 255         # верхняя половина непрозрачная
    ovl[2:, :, 3] = 0           # нижняя — прозрачная
    blend_bgra(frame, ovl, 3, 3)
    assert frame[3, 3, 2] == 200
    assert frame[5, 3].tolist() == [0, 0, 0]      # прозрачная часть не рисуется
    assert frame[0, 0].tolist() == [0, 0, 0]      # вне накладки кадр не тронут


def test_blend_bgra_clips_at_frame_edges():
    frame = np.zeros((10, 10, 3), np.uint8)
    ovl = np.full((6, 6, 4), 255, np.uint8)
    blend_bgra(frame, ovl, -3, -3)                # частично за левым верхним углом
    assert frame[0, 0, 0] == 255
    assert frame[3, 3, 0] == 0
    blend_bgra(frame, ovl, 100, 100)              # целиком снаружи — без ошибок
    assert frame[9, 9, 0] == 0
