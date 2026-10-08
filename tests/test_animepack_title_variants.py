"""New title modes survive UI settings, generation and SIQ export."""
import json
import zipfile
from unittest.mock import Mock

import pytest
import animepack as ap
import animepack_tab

NEW_KINDS = ("definitions",)
TEXTS = {
    "definitions": "Документ для записи сведений о прекращении жизни",
}


def test_removed_title_modes_are_not_exposed():
    """Убранные виды загадок по названию нигде не предлагаются.

    «Зашифрованное название» ушло вслед за ними по просьбе пользователя:
    локальный сдвиг алфавита решался механически."""
    for kind in ("google_query", "product_description", "legal_document",
                 "cipher"):
        assert kind not in ap.TITLE_KINDS
        assert kind not in ap.KIND_TITLES


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_controls_roundtrip_and_key_requirement(qapp, kind):
    tab = animepack_tab.AnimePackTab()
    try:
        tab.chk_titles.setChecked(True)
        tab.chk_anagram.setChecked(False)
        getattr(tab, "chk_" + kind).setChecked(True)
        tab.chk_songs.setChecked(False)
        saved = tab.get_settings()
        tab.apply_settings(saved)
        assert tab.mix.keys() == ["titles"]
        assert tab.title_mix.shares()[kind] == 100
        settings = tab.collect()
        assert getattr(settings, "pack_" + kind)
        settings.gemini_key = ""
        assert any("Gemini" in p for p in settings.validate())
        assert tab.group_gemini.isVisibleTo(tab)
    finally:
        tab.cleanup()


@pytest.mark.parametrize("kinds", [NEW_KINDS])
def test_new_modes_generate_pack(tmp_path, monkeypatch, kinds):
    options = {f"pack_{kind}": True for kind in kinds}
    options.update({f"pct_{kind}": 100 // len(kinds) for kind in kinds})
    settings = ap.PackSettings(rounds=1, themes=1, questions=len(kinds),
        pct_songs=0, gemini_key="test", out_dir=str(tmp_path), **options)
    client = Mock()

    def respond(prompt, schema):
        rows = json.loads(prompt.split("\n")[-1])
        if "eligible" in schema["properties"]["items"]["items"]["properties"]:
            return {"items": [{"id": row["id"], "eligible": True} for row in rows]}
        assert {row["kind"] for row in rows} == set(TEXTS)
        assert all(row["title"] == "Тетрадь смерти" for row in rows)
        assert "ТОЛЬКО по словам исходного title" in prompt
        assert all(set(row) == {"id", "kind", "title"} for row in rows)
        return {"items": [{"id": row["id"], "text": TEXTS[row["kind"]]} for row in rows]}

    client.generate_json.side_effect = respond
    gen = ap.AnimePackGenerator(settings, gemini=client,
                               frames_history_path=str(tmp_path / "frames.json"))
    candidates = [ap.SongCandidate(song={}, anime={"id": i + 1,
        "russian": "Тетрадь смерти", "name": "Death Note"}, kind="op")
        for i in range(len(kinds))]
    monkeypatch.setattr(gen, "iter_candidates", lambda: iter(candidates))
    monkeypatch.setattr(gen, "download_images", lambda cand: None)
    result = gen.run()
    assert {cand.kind for cand in result.songs} == set(kinds)
    assert client.generate_json.call_count == 2
    with zipfile.ZipFile(result.path) as archive:
        xml = archive.read("content.xml").decode()
    for kind in kinds:
        assert TEXTS[kind] in xml
    assert "Тетрадь смерти" in xml
    assert all(not cand.plot_answers for cand in result.songs)
