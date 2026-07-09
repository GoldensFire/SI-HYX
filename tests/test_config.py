# -*- coding: utf-8 -*-
"""Тесты config.py: разрешение путей к инструментам, http-обёртки, константы."""
import json
import os
import sys

import pytest

import config


# ── strip_default_tag ────────────────────────────────────────────────────────
class TestStripDefaultTag:
    def test_strips(self):
        assert config.strip_default_tag("mp4 (по умолчанию)") == "mp4"

    def test_no_tag(self):
        assert config.strip_default_tag("mkv") == "mkv"

    def test_non_string_passthrough(self):
        assert config.strip_default_tag(5) == 5
        assert config.strip_default_tag(None) is None

    def test_whitespace_trimmed(self):
        assert config.strip_default_tag("  webm (по умолчанию)  ") == "webm"


# ── cpu_thread_count ─────────────────────────────────────────────────────────
class TestCpuThreadCount:
    def test_normal(self, monkeypatch):
        monkeypatch.setattr(config.os, "cpu_count", lambda: 8)
        assert config.cpu_thread_count() == 8

    def test_none_falls_back_to_env(self, monkeypatch):
        monkeypatch.setattr(config.os, "cpu_count", lambda: None)
        monkeypatch.setenv("NUMBER_OF_PROCESSORS", "12")
        assert config.cpu_thread_count() == 12

    def test_no_env_default_four(self, monkeypatch):
        monkeypatch.setattr(config.os, "cpu_count", lambda: None)
        monkeypatch.setenv("NUMBER_OF_PROCESSORS", "")
        assert config.cpu_thread_count() == 4

    def test_bad_env_default_four(self, monkeypatch):
        monkeypatch.setattr(config.os, "cpu_count", lambda: 0)
        monkeypatch.setenv("NUMBER_OF_PROCESSORS", "мусор")
        assert config.cpu_thread_count() == 4


# ── _resolve_tool / _resolve_asset / _resolve_ffmpeg7_dir ────────────────────
class TestResolveTool:
    def test_found_next_to_exe(self, monkeypatch, tmp_path):
        exe = "ffmpeg.exe" if config.IS_WIN else "ffmpeg"
        (tmp_path / exe).write_bytes(b"MZ")
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        assert config._resolve_tool("ffmpeg") == str(tmp_path / exe)

    def test_found_in_bin(self, monkeypatch, tmp_path):
        exe = "ffmpeg.exe" if config.IS_WIN else "ffmpeg"
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / exe).write_bytes(b"MZ")
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        assert config._resolve_tool("ffmpeg") == str(tmp_path / "bin" / exe)

    def test_not_found_returns_name(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        real_isfile = os.path.isfile
        monkeypatch.setattr(
            config.os.path, "isfile",
            lambda p: False if "уникум" in p else real_isfile(p))
        assert config._resolve_tool("уникум") == "уникум"

    def test_resolve_asset_found(self, monkeypatch, tmp_path):
        (tmp_path / "icon.xyz").write_bytes(b"ICO")
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        assert config._resolve_asset("icon.xyz") == str(tmp_path / "icon.xyz")

    def test_resolve_asset_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        real_isfile = os.path.isfile
        monkeypatch.setattr(
            config.os.path, "isfile",
            lambda p: False if "нет_такого" in p else real_isfile(p))
        assert config._resolve_asset("нет_такого.бин") is None

    def test_ffmpeg7_dir_found(self, monkeypatch, tmp_path):
        exe = "ffmpeg.exe" if config.IS_WIN else "ffmpeg"
        d = tmp_path / "bin" / "ffmpeg7"
        d.mkdir(parents=True)
        (d / exe).write_bytes(b"MZ")
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        assert config._resolve_ffmpeg7_dir() == str(d)


# ── ytdlp_base_cmd / _bin_dirs / subprocess_env / deno_available ─────────────
class TestYtdlpBaseCmd:
    def test_bundled_exe(self, monkeypatch, tmp_path):
        exe = "yt-dlp.exe" if config.IS_WIN else "yt-dlp"
        (tmp_path / exe).write_bytes(b"MZ")
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        assert config.ytdlp_base_cmd() == [str(tmp_path / exe)]

    def test_system_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        real_isfile = os.path.isfile
        monkeypatch.setattr(
            config.os.path, "isfile",
            lambda p: False if "yt-dlp" in p.lower() else real_isfile(p))
        monkeypatch.setattr(config.shutil, "which",
                            lambda n: r"C:\tools\yt-dlp.exe" if n == "yt-dlp" else None)
        assert config.ytdlp_base_cmd() == [r"C:\tools\yt-dlp.exe"]

    def test_dev_fallback_python_module(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        real_isfile = os.path.isfile
        monkeypatch.setattr(
            config.os.path, "isfile",
            lambda p: False if "yt-dlp" in p.lower() else real_isfile(p))
        monkeypatch.setattr(config.shutil, "which", lambda n: None)
        assert config.ytdlp_base_cmd() == [sys.executable, "-m", "yt_dlp"]

    def test_frozen_no_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        real_isfile = os.path.isfile
        monkeypatch.setattr(
            config.os.path, "isfile",
            lambda p: False if "yt-dlp" in p.lower() else real_isfile(p))
        monkeypatch.setattr(config.shutil, "which", lambda n: None)
        monkeypatch.setattr(config.sys, "frozen", True, raising=False)
        assert config.ytdlp_base_cmd() is None


class TestBinDirsEnv:
    def test_bin_dirs_unique_existing(self, monkeypatch, tmp_path):
        (tmp_path / "bin").mkdir()
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        dirs = config._bin_dirs()
        assert str(tmp_path) in dirs
        assert str(tmp_path / "bin") in dirs
        assert len(dirs) == len(set(dirs))

    def test_subprocess_env_path_prepended(self, monkeypatch, tmp_path):
        (tmp_path / "bin").mkdir()
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        env = config.subprocess_env()
        first = env["PATH"].split(os.pathsep)[0]
        assert first == str(tmp_path)
        # исходное окружение не испорчено
        assert os.environ["PATH"] != env["PATH"]

    def test_deno_available_bundled(self, monkeypatch, tmp_path):
        exe = "deno.exe" if config.IS_WIN else "deno"
        (tmp_path / exe).write_bytes(b"MZ")
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        assert config.deno_available() is True

    def test_deno_unavailable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "app.exe")])
        real_isfile = os.path.isfile
        monkeypatch.setattr(
            config.os.path, "isfile",
            lambda p: False if p.lower().endswith(("deno", "deno.exe")) else real_isfile(p))
        monkeypatch.setattr(config.shutil, "which", lambda n: None)
        assert config.deno_available() is False


# ── _hw_decode_device_types ──────────────────────────────────────────────────
class TestHwDecode:
    def _write_settings(self, tmp_path, data):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return str(p)

    def test_default_enabled(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "SETTINGS_FILE",
                            str(tmp_path / "нет_файла.json"))
        assert config._hw_decode_device_types() == "d3d11va,dxva2"

    def test_user_disabled(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "SETTINGS_FILE",
                            self._write_settings(tmp_path, {"video_hw_decode": False}))
        assert config._hw_decode_device_types() == ""

    def test_software_render_disables(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "SETTINGS_FILE",
                            self._write_settings(tmp_path,
                                                 {"video_software_render": True,
                                                  "video_hw_decode": True}))
        assert config._hw_decode_device_types() == ""

    def test_enabled_explicit(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "SETTINGS_FILE",
                            self._write_settings(tmp_path, {"video_hw_decode": True}))
        assert config._hw_decode_device_types() == "d3d11va,dxva2"


# ── fail_and_exit ────────────────────────────────────────────────────────────
class TestFailAndExit:
    def test_exits_with_code_1(self, capsys):
        with pytest.raises(SystemExit) as e:
            config.fail_and_exit("фатальная ошибка")
        assert e.value.code == 1
        assert "фатальная ошибка" in capsys.readouterr().out

    def test_prints_traceback(self, capsys):
        try:
            raise ValueError("исходная причина")
        except ValueError as exc:
            with pytest.raises(SystemExit):
                config.fail_and_exit("ошибка", exc)
        err = capsys.readouterr().err
        assert "исходная причина" in err


# ── константы ────────────────────────────────────────────────────────────────
class TestConstants:
    def test_format_options_shapes(self):
        for label, fmt in config.FORMAT_OPTIONS.items():
            assert "bestvideo" in fmt and "bestaudio" in fmt

    def test_allowed_audio_subset_of_media(self):
        assert config.ALLOWED_AUDIO <= config.ALLOWED_MEDIA

    def test_ribbon_extends_img_with_svg(self):
        assert config.RIBBON_IMG == config.ALLOWED_IMG | {".svg"}
        assert ".svg" not in config.ALLOWED_IMG

    def test_cookie_paths_inside_config_dir(self):
        for p in config.COOKIE_PATHS.values():
            assert p.startswith(config.CONFIG_DIR)

    def test_app_title(self):
        assert config.APP_NAME in config.APP_TITLE
        assert config.APP_VERSION in config.APP_TITLE

    def test_merge_options(self):
        assert set(config.MERGE_OPTIONS) == {"mp4", "mkv", "webm"}


# ── иконки (нужен QApplication) ──────────────────────────────────────────────
@pytest.mark.qt
class TestIcons:
    def test_get_icon(self, qapp):
        icon = config.get_icon("fa5s.play")
        assert not icon.isNull()

    def test_get_icon_pixmap(self, qapp):
        pm = config.get_icon_pixmap("fa5s.play", size=24)
        assert not pm.isNull()
        # физический размер учитывает devicePixelRatio (HiDPI) — сверяем логический
        assert round(pm.width() / pm.devicePixelRatio()) == 24

    def test_icon_html(self, qapp):
        html = config.icon_html("fa5s.play", size=16)
        assert html.startswith("<img src='data:image/png;base64,")
        assert "width='16'" in html

    def test_status_html_escapes(self, qapp):
        out = config.status_html("fa5s.check", "<script>alert(1)</script>")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out
