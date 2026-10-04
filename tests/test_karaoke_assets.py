"""Interrupted lazy asset setup does not publish a partially extracted CLI."""
from types import SimpleNamespace
import zipfile

from karaoke import ai_assets


def test_incomplete_cli_extraction_is_repaired_before_use(tmp_path, monkeypatch):
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("release/whisper-cli.exe", b"complete executable")
    directory = tmp_path / "whisper-cpp-1.8.4.1"
    partial = directory / "release/whisper-cli.exe"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"partial")
    monkeypatch.setattr(ai_assets, "ROOT", tmp_path)
    monkeypatch.setattr(ai_assets, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setattr(ai_assets, "download", lambda *a: archive)
    binary = ai_assets.cpp_binary()
    assert binary.read_bytes() == b"complete executable"
    assert (directory / ".ready").is_file()
