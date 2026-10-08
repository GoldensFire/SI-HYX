"""Reuse already rendered questions when extending a real karaoke pack."""
import json
from pathlib import Path
import zipfile

import animepack as ap


def load(directory):
    directory = Path(directory)
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    rows = json.loads((directory / "candidates.json").read_text(encoding="utf-8"))
    songs = [ap.SongCandidate(**row) for row in rows]
    if not all(c.has_video and c.music_effect == "karaoke" for c in songs):
        raise ValueError("Возобновление требует готовых караоке-вопросов.")
    return songs, Path(result["package"])


def restore(generator, songs, package):
    folder = Path(generator.folder)
    with zipfile.ZipFile(package) as archive:
        # Every requested member is an explicitly constructed basename. Never
        # extract an archive's paths into the workspace.
        for i, candidate in enumerate(songs, 1):
            old_video, old_poster = candidate.video_out, candidate.poster_file
            candidate.media_base = "resumed-" + str(i) + "-" + candidate.file_base
            candidate.poster_name = "resumed-" + str(i) + "-" + old_poster
            for source, destination in (
                ("Video/" + old_video, folder / "Video" / candidate.video_out),
                ("Karaoke/" + Path(old_video).stem + ".ass",
                 folder / "Video" / (Path(candidate.video_out).stem + ".ass")),
                ("Images/" + old_poster, folder / "Images" / candidate.poster_file)):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(source))


def install(generator, previous, package, count):
    original = generator.select_songs
    remaining = count - len(previous)
    if remaining < 1:
        raise ValueError("В предыдущем паке уже достаточно вопросов.")

    def select():
        # The normal selector fills only the missing slots. Existing distinct
        # songs are removed from its catalogue by the caller.
        themes, questions = generator.s.themes, generator.s.questions
        average = generator.s.song_level_avg
        required = (average * count - sum(c.level for c in previous)) / remaining
        if not 1 <= required <= 15:
            raise ValueError(f"Добор не может дать среднюю {average}: нужен уровень {required:.2f}.")
        generator.s.song_level_avg = round(required)
        generator.log(f"Добор {remaining} вопросов: нужна средняя {required:.2f}, "
                      f"цель отбора {generator.s.song_level_avg}.")
        generator.s.themes, generator.s.questions = 1, remaining
        try:
            extra = original()
        finally:
            generator.s.themes, generator.s.questions = themes, questions
            generator.s.song_level_avg = average
        restore(generator, previous, package)
        return previous + extra
    generator.select_songs = select
