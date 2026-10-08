"""The artifact audit catches bad answers, repeats and composition drift."""
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
import animepack as ap

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from manga_pack_audit import audit


def fixture_rows():
    settings = ap.PackSettings(rounds=1, themes=1, questions=3, pack_manga=True,
                              pct_manga=100, pct_songs=0, manga_strict_targets=True,
                              manga_pct_manhwa=33, manga_pct_manhua=33,
                              manga_level_avg=6, manga_level_min=3, manga_level_max=10)
    rows = [dict(title=f"Comic {i}", mal=i, kind=kind, level=6,
                 franchise_keys=[f"series-{i}"], page=f"https://reader.test/{i}")
            for i, kind in enumerate(("manga", "manhwa", "manhua"), 1)]
    questions = [ET.fromstring('<question xmlns="test"><right><answer>Comic</answer>'
                              '</right></question>') for _ in rows]
    return settings, rows, questions


def test_validated_pack_contains_all_three_editions_and_answers():
    settings, rows, questions = fixture_rows()
    assert audit(settings, rows, questions, {"s": "test"})["exact_composition"]


@pytest.mark.parametrize("failure", ["edition", "level", "title", "identity", "franchise", "source", "answer"])
def test_invalid_artifact_is_not_reported_as_verified(failure):
    settings, rows, questions = fixture_rows()
    if failure == "edition":
        rows[2]["kind"] = "manga"
    elif failure == "level":
        rows[2]["level"] = 15
    elif failure == "title":
        rows[2]["title"] = rows[0]["title"]
    elif failure == "identity":
        rows[2]["mal"] = rows[0]["mal"]
    elif failure == "franchise":
        rows[2]["franchise_keys"] = rows[0]["franchise_keys"]
    elif failure == "source":
        rows[2]["page"] = ""
    else:
        questions[0] = ET.fromstring('<question xmlns="test"><right/></question>')
    with pytest.raises(RuntimeError):
        audit(settings, rows, questions, {"s": "test"})
