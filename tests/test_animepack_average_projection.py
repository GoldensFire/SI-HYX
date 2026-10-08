"""The next candidate must not push an already balanced pack off target."""
from types import SimpleNamespace

from animepack import FRAME_KIND, PackSettings
from test_animepack_extras import _gen


def test_hard_candidate_cannot_jump_out_of_target_band():
    gen = _gen(PackSettings(level_avg=2))
    candidate = SimpleNamespace(kind=FRAME_KIND, level=10)
    assert not gen._level_fits(candidate, [2, 2, 2], FRAME_KIND)
    assert gen._level_fits(SimpleNamespace(kind=FRAME_KIND, level=2), [2, 2, 2], FRAME_KIND)


def test_inflight_questions_contribute_to_projected_average():
    gen = _gen(PackSettings(level_avg=2))
    # Разброс вокруг середины допустим (drift_limit), но качающиеся вопросы
    # в него входят: с тремя тройками «в полёте» пятёрка уже не проходит.
    candidate = SimpleNamespace(kind=FRAME_KIND, level=5)
    flying = [SimpleNamespace(kind=FRAME_KIND, level=3)] * 3
    assert gen._level_fits(candidate, [2, 2, 2], FRAME_KIND)
    assert not gen._level_fits(candidate, [2, 2, 2], FRAME_KIND, flying)
    assert gen._level_fits(SimpleNamespace(kind=FRAME_KIND, level=1), [2, 2, 2], FRAME_KIND, flying)
