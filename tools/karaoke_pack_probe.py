"""Generate, time and verify real karaoke packs through public generator APIs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile
import time
import zipfile
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import animepack as ap
from karaoke.matching import metadata_matches
from karaoke.mugen import Mugen

MAL_IDS = [38000, 30, 16498, 1535, 11757, 5114, 1, 205, 269, 20, 1735,
           1575, 2001, 4181, 23273, 4224, 5680, 19647, 6547, 9756, 9253,
           30276, 31964, 21, 28999, 37999, 37521, 40748, 41457, 44511,
           52991, 52034, 37450, 9253, 12189, 20507, 457, 226, 849, 6702]


def verify_package(path, ffprobe, run, expected=24):
    with zipfile.ZipFile(path) as archive:
        xml = ET.fromstring(archive.read("content.xml"))
        manifest = json.loads(archive.read("karaoke.json"))
        videos = [name for name in archive.namelist() if name.startswith("Video/")]
        questions = xml.findall(".//{*}question")
        if any(count != expected for count in (len(questions), len(videos), len(manifest["questions"]))):
            raise ValueError(f"Пак должен содержать ровно {expected} вопросов и караоке-видео.")
        for question in questions:
            prompt = question.find(".//{*}param[@name='question']")
            answer = question.find(".//{*}param[@name='answer']")
            if prompt is None or answer is None:
                raise ValueError("Вопрос или ответ отсутствует.")
            if "караоке" in " ".join(prompt.itertext()).casefold():
                raise ValueError("В вопросе не должно быть слова «караоке».")
            posters = [item.text for item in answer.findall("{*}item") if item.get("type") == "image"]
            if len(posters) != 1 or "Images/" + posters[0] not in archive.namelist():
                raise ValueError("В ответе отсутствует постер.")
            if "нет оценки" in " ".join(answer.itertext()):
                raise ValueError("В проверочном паке отсутствует рейтинг MAL.")
        report = []
        references = [item.text for question in questions
                      for item in question.findall(".//{*}item") if item.get("type") == "video"]
        if sorted(references) != sorted(row["file"] for row in manifest["questions"]):
            raise ValueError("Вопросы не ссылаются на все свои видео ровно один раз.")
        with tempfile.TemporaryDirectory(prefix="karaoke-verify-") as directory:
            for row in manifest["questions"]:
                video = "Video/" + row["file"]
                if video not in videos or row["ai_used"]:
                    raise ValueError("Проверочный пак должен использовать готовые тайминги.")
                subtitle = "Karaoke/" + Path(row["file"]).stem + ".ass"
                text = archive.read(subtitle).decode("utf-8-sig")
                if r"\kf" not in text:
                    raise ValueError("В ASS нет karaoke sweep.")
                if any(r"\kf" in line for line in text.splitlines() if ",Translation," in line):
                    raise ValueError("Перевод не должен подсвечиваться.")
                if not row["translation_languages"] and any(
                        line.startswith("Dialogue:") and ",Translation," in line for line in text.splitlines()):
                    raise ValueError("При выключенном переводе в ASS есть лишняя строка.")
                if row.get("highlight_colour") and (
                        "Style: Romaji,Karaoke Rounded,64," not in text
                        or any(tag in text for tag in (r"\fad", r"\move", r"\t(", r"\frz"))):
                    raise ValueError("Неверный karaoke-стиль или лишние анимации текста.")
                if row.get("crop_alignment") != "word" or r"\pos(640," not in text:
                    raise ValueError("Нужны начало целого слова и текст по центру.")
                target = Path(directory) / "video.mp4"
                target.write_bytes(archive.read(video))
                code, stdout, stderr = run([ffprobe, "-v", "error", "-show_streams",
                                            "-show_format", "-of", "json", str(target)], timeout=30)
                if code:
                    raise ValueError(stderr)
                probe = json.loads(stdout)
                streams = {item["codec_type"]: item for item in probe["streams"]}
                if streams["video"]["codec_name"] != "av1" or streams["audio"]["codec_name"] != "opus":
                    raise ValueError("Неверные кодеки караоке-видео.")
                seconds = float(probe["format"]["duration"])
                if abs(seconds - row["output_duration"]) > .15:
                    raise ValueError("Длительность ролика отличается от таймингов.")
                ffmpeg = shutil.which("ffmpeg") or ap.FFMPEG
                code, _, error = run([ffmpeg, "-v", "error", "-i", str(target),
                                      "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], timeout=60)
                if code or error.strip():
                    raise ValueError("Видео или звук не декодируются: " + error[-300:])
                report.append({"song": row["title"], "artist": row["artist"],
                               "kind": row["kind"], "source": row["source"],
                               "duration": seconds, "effect": row["effect"],
                               "translation": row["translation_languages"],
                               "crop_start": row["crop_start"],
                               "requested_crop_start": row["requested_crop_start"],
                               "crf": row["crf"], "preset": row["preset"],
                               "decode_ok": True,
                               "highlight": row.get("highlight_colour"),
                               "recording": row["recording"]})
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--crf", type=int, default=ap.VIDEO_CRF)
    parser.add_argument("--preset", type=int, default=10)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--mixed-effects", action="store_true")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit должен быть положительным")
    started = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=True)
    ap.FFMPEG = shutil.which("ffmpeg") or ap.FFMPEG
    ap.FFPROBE = shutil.which("ffprobe") or ap.FFPROBE
    themes = 3 if args.limit == 12 else 4 if args.limit == 24 else 1
    settings = ap.PackSettings(title=f"Аниме · {args.limit} песен", rounds=1,
                               themes=themes, questions=args.limit // themes, audio_cut=20,
                               karaoke_enabled=True, karaoke_percent=100,
                               karaoke_ai_fallback=False, karaoke_crf=args.crf,
                               karaoke_preset=args.preset,
                               images=False, parallel=1, sort_by_index=False)
    if settings.validate():
        parser.error("; ".join(settings.validate()))
    generator = ap.AnimePackGenerator(settings, log=lambda text: print(text, flush=True))
    generator.prepare_dirs()
    # Retain originals and final media so the result can be reviewed/reproduced.
    work = args.output / "media"
    work.mkdir(exist_ok=True)
    generator.cleanup()
    generator.folder = str(work)
    for name in ("Audio", "Video", "Images"):
        (work / name).mkdir(exist_ok=True)
    provider = Mugen(generator.karaoke_resolver.http)
    catalog = args.catalog or args.output / "anisong-catalog.json"
    if catalog.is_file():
        songs = json.loads(catalog.read_text(encoding="utf-8"))
    else:
        songs = generator.anisong.songs_by_mal_ids(MAL_IDS)
        catalog.write_text(json.dumps(songs, ensure_ascii=False, indent=1), encoding="utf-8")
    catalog_seconds = time.monotonic() - started
    card_started = time.monotonic()
    # Use full cards just like normal generation: score, poster and answer names.
    ids = sorted({int((row.get("linked_ids") or {}).get("myanimelist") or 0)
                  for row in songs} - {0})
    cards = {}
    for offset in range(0, len(ids), 50):
        for card in generator._animes_by_ids(ids[offset:offset + 50]):
            cards[int(card.get("malId") or card.get("id") or 0)] = card
    card_seconds = time.monotonic() - card_started
    # Inserts first, then alternate OP/ED, to exercise every supported type.
    random.Random(37).shuffle(songs)
    songs.sort(key=lambda row: {"insert": 0, "ending": 1, "opening": 2}.get(ap.song_kind(row.get("songType")), 3))
    made, rejected, seen = [], [], set()
    selection_started = time.monotonic()
    search_seconds = 0.0
    attempts = []
    for song in songs:
        kind = ap.song_kind(song.get("songType"))
        if not song.get("audio") or kind not in ap.SONG_KINDS:
            continue
        # Keep room for OP/ED/OST in validation packs of different sizes.
        if args.limit >= 3 and kind in ("insert", "ending"):
            cap = max(1, args.limit // (6 if kind == "insert" else 3))
            if sum(c.base_kind == kind for c in made) >= cap:
                continue
        name, artist = str(song.get("songName") or ""), str(song.get("songArtist") or "")
        key = (name.casefold(), artist.casefold())
        if key in seen:
            continue
        seen.add(key)
        attempt_started, previous_count = time.monotonic(), len(made)
        try:
            search_started = time.monotonic()
            tracks = list(provider.search(name, artist))
            search_seconds += time.monotonic() - search_started
            if not any(metadata_matches(name, artist, float(song.get("songLength") or 0), t) for t in tracks):
                continue
            number = len(made) + 1
            mal = (song.get("linked_ids") or {}).get("myanimelist")
            card = cards.get(int(mal or 0))
            if not card:
                rejected.append({"song": name, "error": "Нет полной карточки аниме"})
                continue
            candidate = ap.SongCandidate(song, card, kind=kind,
                                         music_effect="karaoke", media_base=f"{number:02d}-{name[:70]}")
            candidate.media_base = ap.safe_filename(candidate.media_base, str(number))
            candidate.trim_start = min(30, max(0, int(float(song.get("songLength") or 90) - 25)))
            # Exercise an actual changed tempo/pitch/noise/band-pass as well.
            settings.karaoke_effect = (["original", "pitch", "noise", "bandpass", "tempo"][len(made) % 5]
                                      if args.mixed_effects else "original")
            settings.karaoke_pitch = 2
            settings.karaoke_tempo = 1.25
            if generator.download_audio(candidate):
                with generator._timed("постеры в ответах"):
                    generator.download_images(candidate)
                if not candidate.has_poster or candidate.score <= 0:
                    raise ValueError("Нет постера или рейтинга для проверочного пака")
                made.append(candidate)
                print(f"READY {len(made)}/{args.limit}: {name}", flush=True)
            else:
                rejected.append({"song": name, "artist": artist})
        except Exception as error:
            rejected.append({"song": name, "error": str(error)})
            print(f"REJECT {name}: {error}", flush=True)
        finally:
            attempts.append({"song": name, "seconds": time.monotonic() - attempt_started,
                             "accepted": len(made) > previous_count})
        (args.output / "progress.json").write_text(json.dumps({
            "ready": len(made), "songs": [c.song_name for c in made], "rejected": rejected},
            ensure_ascii=False, indent=2), encoding="utf-8")
        if len(made) >= args.limit:
            break
    if len(made) != args.limit:
        raise RuntimeError(f"Получилось {len(made)} из {args.limit}; смотрите progress.json.")
    selection_seconds = time.monotonic() - selection_started
    package_started = time.monotonic()
    path = generator.write_package(made, str(args.output / f"Аниме-Песни-{args.limit}.siq"))
    generation_seconds = time.monotonic() - started
    stages = {stage: sum(b - a for a, b in spans)
              for stage, spans in generator._stage_spans.items()}
    timings = {"catalog_and_setup": catalog_seconds, "anime_cards": card_seconds,
               "song_selection_and_media": selection_seconds, "source_search": search_seconds,
               "package": time.monotonic() - package_started, "stages": stages}
    verify_started = time.monotonic()
    report = verify_package(path, ap.FFPROBE, generator._run_capture, expected=args.limit)
    (args.output / "verification.json").write_text(json.dumps({
        "package": path, "generation_seconds": generation_seconds,
        "execution": "sequential validation harness",
        "verification_seconds": time.monotonic() - verify_started,
        "settings": settings.to_dict(), "timings": timings,
        "questions": report, "attempts": attempts,
        "rejected": rejected}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"GENERATION {generation_seconds:.2f}s; {len(made) / generation_seconds * 60:.2f} songs/min", flush=True)
    print("PACKAGE " + path, flush=True)


if __name__ == "__main__":
    main()
