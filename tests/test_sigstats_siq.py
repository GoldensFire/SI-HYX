# -*- coding: utf-8 -*-
"""Тесты sigstats/siq.py — скачивание и разбор .siq (v4 scenario и v5 params)."""
import zipfile
from pathlib import Path

import pytest

from sigstats import siq
from sigstats import config as scfg
from conftest import FakeResponse, FakeSession


@pytest.fixture(autouse=True)
def isolated_media(tmp_path, monkeypatch):
    monkeypatch.setattr(scfg, "MEDIA_DIR", Path(tmp_path / "media"))
    monkeypatch.setattr(scfg, "PACKAGES_DIR", Path(tmp_path / "packages"))
    # предсказуемая длительность медиа без настоящего ffprobe
    monkeypatch.setattr(siq, "_probe_duration", lambda p: 7.0)
    siq._DURATION_CACHE.clear()
    siq._CODEC_CACHE.clear()
    siq._DIM_CACHE.clear()


V5_XML = """<?xml version="1.0" encoding="utf-8"?>
<package name="Пак v5" version="5">
  <rounds>
    <round name="Раунд 1">
      <themes>
        <theme name="Тема 😃А">
          <questions>
            <question price="100">
              <params>
                <param name="question" type="content">
                  <item>Короткий текст</item>
                </param>
              </params>
              <right><answer>Ответ раз</answer><answer>Ответ два</answer></right>
            </question>
            <question price="200">
              <params>
                <param name="question" type="content">
                  <item type="image" isRef="True">img.png</item>
                </param>
              </params>
              <right><answer>Картинка</answer></right>
            </question>
            <question price="abc">
              <params>
                <param name="question" type="content"><item>Цена-мусор</item></param>
              </params>
              <right><answer>х</answer></right>
            </question>
          </questions>
        </theme>
      </themes>
    </round>
  </rounds>
</package>
"""

V4_XML = """<?xml version="1.0" encoding="utf-8"?>
<package name="Пак v4" version="4">
  <rounds>
    <round name="Р1">
      <themes>
        <theme name="Тема">
          <questions>
            <question price="500">
              <scenario>
                <atom type="image">@old.png</atom>
                <atom>Текст вопроса v4</atom>
                <atom type="marker"></atom>
                <atom type="image">@answer.png</atom>
              </scenario>
              <right><answer>Ответ v4</answer></right>
            </question>
          </questions>
        </theme>
      </themes>
    </round>
  </rounds>
</package>
"""


def _siq(tmp_path, xml, media=None, name="p.siq"):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("content.xml", xml)
        for arc, data in (media or {}).items():
            zf.writestr(arc, data)
    return p


# ── низкоуровневые хелперы ───────────────────────────────────────────────────
class TestXmlHelpers:
    def test_local_strips_ns(self):
        assert siq._local("{http://ns}round") == "round"
        assert siq._local("round") == "round"

    def test_children_and_child(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring("<a><b/><c/><b/></a>")
        assert len(siq._children(root, "b")) == 2
        assert siq._child(root, "c") is not None
        assert siq._child(root, "нет") is None


class TestParseDurAttr:
    @pytest.mark.parametrize("s,expected", [
        ("5", 5.0), ("5.5", 5.5),
        ("01:30", 90.0), ("00:01:30", 90.0),
        ("26", 26.0),
    ])
    def test_valid(self, s, expected):
        assert siq._parse_dur_attr(s) == expected

    @pytest.mark.parametrize("s", [None, "", "abc", "1:xx"])
    def test_invalid(self, s):
        assert siq._parse_dur_attr(s) is None


class TestItemInfo:
    def _el(self, xml):
        import xml.etree.ElementTree as ET
        return ET.fromstring(xml)

    def test_defaults(self):
        info = siq._item_info(self._el("<item>текст</item>"))
        assert info == {"type": "text", "raw": "текст", "is_ref": False,
                        "wait_false": False, "placement": "", "dur_attr": None}

    def test_voice_becomes_audio(self):
        info = siq._item_info(self._el('<item type="voice">@a.mp3</item>'))
        assert info["type"] == "audio"

    def test_flags(self):
        info = siq._item_info(self._el(
            '<item type="image" isRef="TRUE" waitForFinish="False" '
            'placement="Background" duration="00:10">x</item>'))
        assert info["is_ref"] is True
        assert info["wait_false"] is True
        assert info["placement"] == "background"
        assert info["dur_attr"] == 10.0


class TestItemSeconds:
    def _info(self, **kw):
        base = {"type": "text", "raw": "", "is_ref": False,
                "wait_false": False, "placement": "", "dur_attr": None}
        base.update(kw)
        return base

    def test_timer_overrides_everything(self):
        info = self._info(type="video", dur_attr=26.0)
        assert siq._item_seconds(info, None, None) == 26.0

    def test_image_five_seconds(self):
        assert siq._item_seconds(self._info(type="image"), None, None) == 5.0

    def test_text_by_length(self):
        info = self._info(raw="х" * 40)
        assert siq._item_seconds(info, None, None) == pytest.approx(2.0)

    def test_empty_text_zero(self):
        assert siq._item_seconds(self._info(), None, None) == 0.0

    def test_negative_timer_clamped(self):
        assert siq._item_seconds(self._info(dur_attr=-5.0), None, None) == 0.0


class TestContentDuration:
    def _info(self, **kw):
        base = {"type": "text", "raw": "", "is_ref": False,
                "wait_false": False, "placement": "", "dur_attr": None}
        base.update(kw)
        return base

    def test_sequential_sum(self):
        items = [self._info(dur_attr=3.0), self._info(dur_attr=4.0)]
        assert siq._content_duration(items, None, None) == 7.0

    def test_simultaneous_group_max(self):
        # waitForFinish=False связывает элементы в одну группу → максимум
        items = [self._info(dur_attr=3.0, wait_false=True),
                 self._info(dur_attr=10.0)]
        assert siq._content_duration(items, None, None) == 10.0

    def test_media_in_group_wins_over_text(self):
        items = [self._info(type="image", wait_false=True),      # 5 сек
                 self._info(raw="х" * 200)]                        # 10 сек текста
        # в группе с медиа устный текст не считается
        assert siq._content_duration(items, None, None) == 5.0

    def test_background_parallel(self):
        items = [self._info(dur_attr=4.0),
                 self._info(type="audio", placement="background", dur_attr=30.0)]
        assert siq._content_duration(items, None, None) == 30.0

    def test_empty(self):
        assert siq._content_duration([], None, None) == 0.0


# ── _extract_atom ────────────────────────────────────────────────────────────
class TestExtractAtom:
    def test_embedded(self, tmp_path):
        p = _siq(tmp_path, V5_XML, media={"Images/img.png": b"PNGDATA"})
        with zipfile.ZipFile(p) as zf:
            m = siq._extract_atom(zf, "image", "@img.png", tmp_path / "out")
        assert m["embedded"] is True
        assert m["ref"] == "img.png"
        assert Path(m["path"]).read_bytes() == b"PNGDATA"

    def test_percent_encoded_name(self, tmp_path):
        arc = "Video/%D0%9F%D1%80%D0%B8%D0%BC%D0%B5%D1%80.mp4"  # «Пример.mp4»
        p = _siq(tmp_path, V5_XML, media={arc: b"MP4"})
        with zipfile.ZipFile(p) as zf:
            m = siq._extract_atom(zf, "video", "@Пример.mp4", tmp_path / "out")
        assert m["path"] is not None
        assert Path(m["path"]).read_bytes() == b"MP4"

    def test_http_link(self, tmp_path):
        p = _siq(tmp_path, V5_XML)
        with zipfile.ZipFile(p) as zf:
            m = siq._extract_atom(zf, "video", "https://x.example/v.mp4",
                                  tmp_path / "out")
        assert m == {"type": "video", "ref": "https://x.example/v.mp4",
                     "embedded": False, "path": None}

    def test_missing_entry(self, tmp_path):
        p = _siq(tmp_path, V5_XML)
        with zipfile.ZipFile(p) as zf:
            m = siq._extract_atom(zf, "image", "@нет.png", tmp_path / "out")
        assert m["embedded"] is True and m["path"] is None

    def test_plain_text_not_media(self, tmp_path):
        p = _siq(tmp_path, V5_XML)
        with zipfile.ZipFile(p) as zf:
            assert siq._extract_atom(zf, "text", "просто текст", tmp_path) is None

    def test_empty_raw(self, tmp_path):
        p = _siq(tmp_path, V5_XML)
        with zipfile.ZipFile(p) as zf:
            assert siq._extract_atom(zf, "image", "", tmp_path) is None


# ── read_package_name ────────────────────────────────────────────────────────
class TestReadPackageName:
    def test_ok(self, tmp_path):
        p = _siq(tmp_path, V5_XML)
        assert siq.read_package_name(p) == "Пак v5"

    def test_capital_content(self, tmp_path):
        p = tmp_path / "c.siq"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("Content.xml", V5_XML)
        assert siq.read_package_name(p) == "Пак v5"

    def test_nested_content(self, tmp_path):
        p = tmp_path / "n.siq"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("data/content.xml", V5_XML)
        assert siq.read_package_name(p) == "Пак v5"

    def test_no_content(self, tmp_path):
        p = tmp_path / "e.siq"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("readme.txt", "x")
        assert siq.read_package_name(p) is None

    def test_not_a_zip(self, tmp_path):
        p = tmp_path / "bad.siq"
        p.write_bytes("не zip".encode("utf-8"))
        assert siq.read_package_name(p) is None

    def test_missing_file(self):
        assert siq.read_package_name("нет_файла.siq") is None


# ── parse_siq (v5 и v4) ──────────────────────────────────────────────────────
class TestParseSiqV5:
    def test_themes(self, tmp_path):
        p = _siq(tmp_path, V5_XML, media={"Images/img.png": b"PNG"})
        themes, questions = siq.parse_siq(p, package_id=1)
        assert len(themes) == 1
        t = themes[0]
        assert t["round_index"] == 0
        assert t["round_name"] == "Раунд 1"
        assert t["name"] == "Тема 😃А"       # оригинал для показа
        assert t["name_norm"] == "тема а"     # нормализованный ключ (без эмодзи)
        assert t["source"] == "siq"

    def test_questions(self, tmp_path):
        p = _siq(tmp_path, V5_XML, media={"Images/img.png": b"PNG"})
        _, questions = siq.parse_siq(p, package_id=1)
        assert len(questions) == 3
        q100 = questions[0]
        assert q100["price"] == 100
        assert q100["text"] == "Короткий текст"
        assert q100["answer"] == "Ответ раз / Ответ два"
        assert q100["media"] == []
        # текст 14 симв/20 + 3 сек текстового ответа
        assert q100["duration_sec"] == pytest.approx(14 / 20 + 3.0, abs=0.01)

    def test_media_extracted(self, tmp_path):
        p = _siq(tmp_path, V5_XML, media={"Images/img.png": b"PNG"})
        _, questions = siq.parse_siq(p, package_id=7)
        q200 = questions[1]
        assert len(q200["media"]) == 1
        m = q200["media"][0]
        assert m["type"] == "image" and m["embedded"] is True
        assert "7" in m["path"]  # media/<package_id>/
        # картинка 5 сек + текстовый ответ 3 сек
        assert q200["duration_sec"] == pytest.approx(8.0)

    def test_bad_price_none(self, tmp_path):
        p = _siq(tmp_path, V5_XML)
        _, questions = siq.parse_siq(p, package_id=1)
        assert questions[2]["price"] is None

    def test_no_rounds(self, tmp_path):
        p = _siq(tmp_path, '<?xml version="1.0"?><package name="x"/>')
        assert siq.parse_siq(p, 1) == ([], [])

    def test_no_content_xml(self, tmp_path):
        p = tmp_path / "e.siq"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("x.txt", "y")
        assert siq.parse_siq(p, 1) == ([], [])

    def test_video_modern_flag(self, tmp_path, monkeypatch):
        xml = V5_XML.replace('type="image" isRef="True">img.png',
                             'type="video" isRef="True">img.png')
        p = _siq(tmp_path, xml, media={"Video/img.png": b"MP4"})
        monkeypatch.setattr(siq, "probe_video_codec", lambda path: "av1")
        _, questions = siq.parse_siq(p, 1)
        assert questions[1]["video_modern"] is True

    def test_video_old_codec(self, tmp_path, monkeypatch):
        xml = V5_XML.replace('type="image" isRef="True">img.png',
                             'type="video" isRef="True">img.png')
        p = _siq(tmp_path, xml, media={"Video/img.png": b"MP4"})
        monkeypatch.setattr(siq, "probe_video_codec", lambda path: "h264")
        _, questions = siq.parse_siq(p, 1)
        assert questions[1]["video_modern"] is False


class TestParseSiqV4:
    def test_scenario_marker_split(self, tmp_path):
        p = _siq(tmp_path, V4_XML, media={"Images/old.png": b"P1",
                                          "Images/answer.png": b"P2"})
        themes, questions = siq.parse_siq(p, 1)
        q = questions[0]
        assert q["price"] == 500
        assert q["text"] == "Текст вопроса v4"
        assert q["answer"] == "Ответ v4"
        # маркер делит сценарий: медиа вопроса — до маркера, ответа — после.
        # (в ветке scenario ref сохраняет ведущий «@» — это поведение кода v4.)
        assert len(q["media"]) == 1 and q["media"][0]["type"] == "image"
        assert len(q["answer_media"]) == 1
        assert "old" in q["media"][0]["ref"]
        assert "answer" in q["answer_media"][0]["ref"]


class TestAnswerTime:
    def test_answer_time_minus_five(self, tmp_path):
        xml = """<?xml version="1.0"?>
<package name="x"><rounds><round name="Р"><themes><theme name="Т"><questions>
<question price="100" duration="00:20">
  <params><param name="question" type="content"><item duration="10">в</item></param></params>
  <right><answer>о</answer></right>
</question>
</questions></theme></themes></round></rounds></package>"""
        p = _siq(tmp_path, xml)
        _, qs = siq.parse_siq(p, 1)
        # вопрос 10 сек + (20 − 5) сек ответной части
        assert qs[0]["duration_sec"] == pytest.approx(25.0)


# ── download_siq ─────────────────────────────────────────────────────────────
class TestDownloadSiq:
    def test_downloads(self, tmp_path):
        s = FakeSession(routes=[("direct_download",
                                 FakeResponse(content=b"SIQZIPDATA"))])
        out = siq.download_siq(s, "42", "Мой пак")
        assert out is not None
        assert out.read_bytes() == b"SIQZIPDATA"
        assert out.name.startswith("42_")
        assert out.suffix == ".siq"

    def test_name_sanitized(self, tmp_path):
        s = FakeSession(routes=[("direct_download", FakeResponse(content=b"x"))])
        out = siq.download_siq(s, "1", 'Пак<>:"/\\|?*!')
        assert out is not None
        for ch in '<>:"/\\|?*':
            assert ch not in out.name

    def test_cached_no_refetch(self, tmp_path):
        s = FakeSession(routes=[("direct_download", FakeResponse(content=b"data"))])
        out1 = siq.download_siq(s, "9", "Пак")
        n_calls = len(s.calls)
        out2 = siq.download_siq(s, "9", "Пак")
        assert out1 == out2
        assert len(s.calls) == n_calls  # второй раз запроса не было

    def test_http_error_none(self, tmp_path):
        s = FakeSession(routes=[("direct_download", FakeResponse(status_code=500))])
        assert siq.download_siq(s, "5", "Пак") is None

    def test_network_error_none(self):
        class Boom(FakeSession):
            def get(self, url, **kw):
                raise OSError("сеть")
        assert siq.download_siq(Boom(), "5", "Пак") is None


# ── ffprobe-обвязка ──────────────────────────────────────────────────────────
class TestFfprobeWrappers:
    def test_ffprobe_prefers_config_path(self, monkeypatch):
        monkeypatch.setattr(siq, "_FFPROBE_CACHED", None)
        monkeypatch.setattr(scfg, "FFPROBE_PATH", r"C:\custom\ffprobe.exe")
        assert siq._ffprobe() == r"C:\custom\ffprobe.exe"

    def test_ffprobe_none_when_missing(self, monkeypatch):
        monkeypatch.setattr(siq, "_FFPROBE_CACHED", None)
        monkeypatch.setattr(scfg, "FFPROBE_PATH", None)
        monkeypatch.setattr(siq.shutil, "which", lambda n: None)
        assert siq._ffprobe() is None

    def test_has_modern_video(self, monkeypatch):
        monkeypatch.setattr(siq, "probe_video_codec",
                            lambda p: {"a.mp4": "hevc", "b.mp4": "h264"}.get(p))
        media = [{"type": "video", "path": "b.mp4"}]
        answer_media = [{"type": "video", "path": "a.mp4"}]
        assert siq._has_modern_video(media, answer_media) is True
        assert siq._has_modern_video(media) is False
        assert siq._has_modern_video([], None) is False
