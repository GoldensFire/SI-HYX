# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""BoxSmoother. Public namespace: dyhit_tracker."""
import dyhit_tracker as _api


class BoxSmoother:
    """Сглаживание рамки [x, y, w, h] фильтром «одно евро» + мёртвая зона.

    strength: 0 — фильтр выключен (рамка отдаётся как есть), 1 — максимум.
    fps нужен, чтобы скорость считалась в пикселях в секунду и настройки не
    зависели от частоты кадров исходника."""

    def __init__(self, strength=0.0, fps=25.0):
        self.strength = float(min(1.0, max(0.0, strength)))
        self.fps = float(fps) if fps and fps > 0 else 25.0
        self._filt = None      # состояние фильтра (cx, cy, w, h)
        self._prev = None      # предыдущее сырое значение — для скорости
        self._vel = None       # сглаженная скорость по каждой из четырёх осей
        self._out = None       # последнее ВЫДАННОЕ значение (для мёртвой зоны)

    @property
    def enabled(self):
        return self.strength > 0.0

    def reset(self, box=None):
        self._filt = self._prev = self._vel = self._out = None
        if box is not None:
            self._filt = self._prev = self._out = _api._to_cxcywh(box)
            self._vel = [0.0, 0.0, 0.0, 0.0]

    def _alpha(self, cutoff):
        """Коэффициент однополюсного фильтра для заданного среза (Гц)."""
        tau = 1.0 / (2.0 * _api.math.pi * max(1e-3, cutoff))
        te = 1.0 / self.fps
        return te / (tau + te)

    def __call__(self, box):
        if not self.enabled:
            return [float(v) for v in box]
        cur = _api._to_cxcywh(box)
        if self._filt is None:
            self.reset(box)
            return list(box)

        s = self.strength
        base_pos = _api._CUTOFF_SLOW * (_api._CUTOFF_FAST / _api._CUTOFF_SLOW) ** s
        base = (base_pos, base_pos,
                base_pos * _api._SIZE_CUTOFF_K, base_pos * _api._SIZE_CUTOFF_K)
        beta = (_api._BETA_POS, _api._BETA_POS, _api._BETA_SIZE, _api._BETA_SIZE)

        a_d = self._alpha(_api._DERIV_CUTOFF)
        raw_v = [(c - p) * self.fps for c, p in zip(cur, self._prev)]
        self._vel = _api._ema(self._vel, raw_v, 1.0 - a_d)
        self._prev = cur

        out = []
        for i in range(4):
            a = self._alpha(base[i] + beta[i] * abs(self._vel[i]))
            self._filt[i] += a * (cur[i] - self._filt[i])
            out.append(self._filt[i])

        # Мёртвая зона, сужающаяся со скоростью (см. константы выше).
        side = max(4.0, _api.math.sqrt(max(1.0, out[2] * out[3])))
        speed = _api.math.hypot(self._vel[0], self._vel[1])
        k = 1.0 / (1.0 + speed / _api._DEAD_V_REF)
        dead = [min(_api._DEAD_MAX, max(_api._DEAD_MIN, side * f)) * k
                for f in (_api._DEAD_POS, _api._DEAD_POS, _api._DEAD_SIZE, _api._DEAD_SIZE)]
        # Выход из зоны — со СМЕЩЕНИЕМ на её ширину, а не скачком к новому
        # значению: иначе накладка, простояв на месте, «щёлкала» на пару пикселей
        # в момент, когда шум наконец пробивал порог.
        held = []
        for o, p, d in zip(out, self._out, dead):
            diff = o - p
            if abs(diff) <= d:
                held.append(p)
            else:
                held.append(o - _api.math.copysign(d, diff))
        self._out = held
        return _api._to_xywh(held)

BoxSmoother.__module__ = _api.__name__
_api.BoxSmoother = BoxSmoother
