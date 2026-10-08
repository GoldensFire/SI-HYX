"""Prepared-question continuation uses plain data and preserves actual resources."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import animepack as ap

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from manga_prepared import capture, restore, safe_name


def test_prepared_resources_and_metadata_survive_continuation(tmp_path):
    source, target, output = tmp_path / "source", tmp_path / "target", tmp_path / "audit"
    for directory in (source / "Images", source / "Video", target / "Images", target / "Video"):
        directory.mkdir(parents=True)
    (source / "Images" / "page.avif").write_bytes(b"page bytes")
    (source / "Video" / "appearance.mp4").write_bytes(b"video bytes")
    candidate = ap.SongCandidate({}, {"malId": 12, "name": "Book", "kind": "manga"},
        kind=ap.MANGA_KIND, media="manga", has_frame=True, frame_name="page.avif",
        frame_url="https://reader.test/page", entrance_frames={"page.avif": "appearance.mp4"})
    capture(SimpleNamespace(folder=str(source), audit_dir=output), candidate)
    generator = SimpleNamespace(folder=str(target), s=ap.PackSettings(), log=lambda *_: None)
    restored = restore(generator, [str(output)])
    assert len(restored) == 1 and restored[0].mal_id == 12
    assert restored[0].frame_url == candidate.frame_url
    assert restored[0]._ready_media == (ap.MANGA_KIND, "original")
    assert (target / "Images" / "page.avif").read_bytes() == b"page bytes"
    assert (target / "Video" / "appearance.mp4").read_bytes() == b"video bytes"


@pytest.mark.parametrize("name", ["../../settings.json", "folder\\file.png", "/absolute.png"])
def test_prepared_resources_cannot_escape_their_folder(name):
    with pytest.raises(ValueError):
        safe_name(name)
