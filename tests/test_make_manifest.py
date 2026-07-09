# -*- coding: utf-8 -*-
"""Тесты make_manifest.py — детерминированный хеш ассетов и manifest.json."""
import hashlib
import json
import os

import pytest

import make_manifest as mm


def _make_app(tmp_path, files):
    """files: {относит_путь: bytes}. Возвращает путь к «приложению»."""
    app = tmp_path / "app"
    for rel, data in files.items():
        p = app / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return str(app)


class TestSha256File:
    def test_matches_hashlib(self, tmp_path):
        f = tmp_path / "x.bin"
        f.write_bytes(b"contents" * 1000)
        assert mm._sha256_file(str(f)) == hashlib.sha256(b"contents" * 1000).hexdigest()

    def test_empty_file(self, tmp_path):
        f = tmp_path / "e.bin"
        f.write_bytes(b"")
        assert mm._sha256_file(str(f)) == hashlib.sha256(b"").hexdigest()


class TestComputeBinSha:
    def test_deterministic(self, tmp_path):
        app = _make_app(tmp_path, {
            "bin/ffmpeg.exe": b"FFMPEG",
            "bin/sub/tool.exe": b"TOOL",
            "models/lama.onnx": b"MODEL",
        })
        h1 = mm.compute_bin_sha(app)
        h2 = mm.compute_bin_sha(app)
        assert h1 == h2
        assert len(h1) == 64

    def test_binver_excluded(self, tmp_path):
        app = _make_app(tmp_path, {"bin/ffmpeg.exe": b"F"})
        before = mm.compute_bin_sha(app)
        (tmp_path / "app" / "bin" / mm.BINVER_NAME).write_text("deadbeef", encoding="ascii")
        after = mm.compute_bin_sha(app)
        assert before == after  # .binver не влияет на хеш

    def test_content_change_changes_hash(self, tmp_path):
        app = _make_app(tmp_path, {"bin/ffmpeg.exe": b"F1"})
        h1 = mm.compute_bin_sha(app)
        (tmp_path / "app" / "bin" / "ffmpeg.exe").write_bytes(b"F2")
        assert mm.compute_bin_sha(app) != h1

    def test_path_included_in_hash(self, tmp_path):
        # одинаковое содержимое, разные имена → разный хеш
        app1 = _make_app(tmp_path / "a", {"bin/a.exe": b"X"})
        app2 = _make_app(tmp_path / "b", {"bin/b.exe": b"X"})
        assert mm.compute_bin_sha(app1) != mm.compute_bin_sha(app2)

    def test_missing_dirs_skipped(self, tmp_path):
        app = _make_app(tmp_path, {"bin/only.exe": b"X"})  # models нет
        assert len(mm.compute_bin_sha(app)) == 64

    def test_empty_app(self, tmp_path):
        app = str(tmp_path / "empty")
        os.makedirs(app)
        assert mm.compute_bin_sha(app) == hashlib.sha256().hexdigest()


class TestCmdBinver:
    def test_writes_binver(self, tmp_path, capsys):
        app = _make_app(tmp_path, {"bin/ffmpeg.exe": b"F", "models/m.onnx": b"M"})
        mm.cmd_binver(app)
        binver = tmp_path / "app" / "bin" / mm.BINVER_NAME
        assert binver.exists()
        assert binver.read_text(encoding="ascii") == mm.compute_bin_sha(app)

    def test_no_bin_exits(self, tmp_path):
        app = str(tmp_path / "nobins")
        os.makedirs(app)
        with pytest.raises(SystemExit) as e:
            mm.cmd_binver(app)
        assert e.value.code == 1


class TestCmdManifest:
    def test_writes_manifest(self, tmp_path):
        app = _make_app(tmp_path, {"bin/ffmpeg.exe": b"F"})
        dist = tmp_path / "dist"
        dist.mkdir()
        update_zip = dist / "update.zip"
        full_zip = dist / "full.zip"
        update_zip.write_bytes(b"UPDATE")
        full_zip.write_bytes(b"FULL-ARCHIVE")

        mm.cmd_manifest(app, str(dist), str(update_zip), str(full_zip))
        manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["bin_sha"] == mm.compute_bin_sha(app)
        assert manifest["update_sha"] == hashlib.sha256(b"UPDATE").hexdigest()
        assert manifest["full_sha"] == hashlib.sha256(b"FULL-ARCHIVE").hexdigest()
        import config
        assert manifest["version"] == config.APP_VERSION

    def test_missing_bin_exits(self, tmp_path):
        app = str(tmp_path / "nobin")
        os.makedirs(app)
        with pytest.raises(SystemExit):
            mm.cmd_manifest(app, str(tmp_path), "u.zip", "f.zip")

    def test_missing_archive_exits(self, tmp_path):
        app = _make_app(tmp_path, {"bin/x.exe": b"X"})
        dist = tmp_path / "dist"
        dist.mkdir()
        with pytest.raises(SystemExit):
            mm.cmd_manifest(app, str(dist), str(dist / "нет.zip"),
                            str(dist / "тоже_нет.zip"))


class TestMain:
    def test_binver_dispatch(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path, {"bin/x.exe": b"X"})
        monkeypatch.setattr(mm.sys, "argv", ["make_manifest.py", "binver", app])
        mm.main()
        assert (tmp_path / "app" / "bin" / mm.BINVER_NAME).exists()

    def test_usage_exits_2(self, monkeypatch, capsys):
        monkeypatch.setattr(mm.sys, "argv", ["make_manifest.py"])
        with pytest.raises(SystemExit) as e:
            mm.main()
        assert e.value.code == 2
        assert "usage" in capsys.readouterr().out.lower()

    def test_unknown_command_usage(self, monkeypatch):
        monkeypatch.setattr(mm.sys, "argv", ["make_manifest.py", "чепуха", "arg"])
        with pytest.raises(SystemExit) as e:
            mm.main()
        assert e.value.code == 2
