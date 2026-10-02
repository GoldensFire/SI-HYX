# -*- coding: utf-8 -*-
"""Задание персонажа сохраняется при любом способе показа портрета."""
import xml.etree.ElementTree as ET

import pytest

import animepack as ap


@pytest.mark.parametrize("kind", [ap.CHAR_KIND, ap.MANGA_KIND])
@pytest.mark.parametrize("entrance", ["none", "frames", "video"])
@pytest.mark.parametrize("hint", [False, True])
def test_character_caption_appears_with_portrait(kind, entrance, hint):
    settings = ap.PackSettings(rounds=1, themes=1, questions=1, hint=hint,
                               entrance_enabled=entrance != "none")
    cand = ap.SongCandidate(
        song={}, anime={"id": 1, "name": "Sample", "russian": "Пример"},
        kind=kind, media="manga" if kind == ap.MANGA_KIND else "anime",
        character={"id": 2, "name": "Герой"}, has_frame=True,
        frame_name="portrait.png")
    if entrance == "frames":
        cand.entrance_frames = {cand.frame_file: "portrait_entrance.mp4"}
    elif entrance == "video":
        cand.entrance_video = "portrait_entrance.mp4"

    root = ET.fromstring(ap.build_content_xml([cand], settings))
    items = root.findall(".//{*}param[@name='question']/{*}item")

    assert len(items) == 2
    caption, portrait = items
    assert caption.text == ap.CHAR_TASK_TEXT
    assert caption.attrib == {"waitForFinish": "False"}
    assert portrait.get("isRef") == "True"
    if entrance == "none":
        assert portrait.get("type") == "image"
        assert portrait.text == cand.frame_file
    else:
        assert portrait.get("type") == "video"
        assert portrait.text == "portrait_entrance.mp4"
    assert portrait.get("duration") == "00:00:04"
