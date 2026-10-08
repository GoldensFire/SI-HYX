"""Retain prepared comic resources and reuse them during this pack's continuation."""
from copy import copy
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import animepack as ap
from si_hyx_parts.animepack.generator_catalog import _franchise_marks
from si_hyx_parts.animepack.ru_popularity_store import service


def safe_name(name):
    if not name or Path(name).name != name or "\\" in name or "/" in name:
        raise ValueError("Недопустимое имя ресурса подготовленного вопроса")
    return name


def resource_names(candidate):
    images = {candidate.frame_file} if candidate.has_frame else set()
    if candidate.has_poster:
        images.add(candidate.poster_file)
    return {"Images": images, "Video": set(candidate.entrance_frames.values())}


def capture(generator, candidate):
    root = generator.audit_dir / "prepared"
    names = resource_names(candidate)
    for folder, resources in names.items():
        target = root / folder
        target.mkdir(parents=True, exist_ok=True)
        for name in resources:
            shutil.copy2(Path(generator.folder) / folder / safe_name(name), target / name)
    payload = {field.name: getattr(candidate, field.name) for field in fields(ap.SongCandidate)}
    checkpoints = root / "candidates"
    checkpoints.mkdir(exist_ok=True)
    key = hashlib.sha256(candidate.frame_file.encode("utf-8")).hexdigest()
    target = checkpoints / f"{candidate.mal_id}-{key[:12]}.json"
    temporary = target.with_suffix(".pending.json")
    temporary.write_text(json.dumps({"version": 1, "candidate": payload,
                                    "level": candidate.level}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


def prepared(generator, root):
    for path in (root / "prepared" / "candidates").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            continue
        candidate = ap.SongCandidate(**data["candidate"])
        if not candidate.is_manga:
            continue
        names = resource_names(candidate)
        if any(not (root / "prepared" / folder / safe_name(name)).is_file()
               for folder, resources in names.items() for name in resources):
            continue
        for folder, resources in names.items():
            for name in resources:
                shutil.copy2(root / "prepared" / folder / name,
                             Path(generator.folder) / folder / name)
        yield candidate


def archive(generator, root):
    report_path = root / "report.json"
    if not report_path.is_file():
        return
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("pack") or not Path(report["pack"]).is_file():
        return
    cache = generator.db_cache
    cards = {str(c.get("malId")): c for c in cache.all_cards("manga")}
    anime = {str(c.get("id")): c for c in cache.all_cards("anime")}
    with zipfile.ZipFile(report["pack"]) as package:
        members = set(package.namelist())
        for row in report["questions"]:
            card = cards.get(str(row["mal"]))
            if not card or card.get("kind") != row["kind"]:
                continue
            candidate = ap.SongCandidate({}, copy(card), kind=ap.MANGA_KIND, media="manga")
            candidate.favorites = cache.memo("manga_favorites", card.get("id"))
            candidate.ru_popularity = service(generator).evaluate(candidate, network=False)
            franchise = str(card.get("franchise") or "")
            parts = cache.franchise(franchise) if franchise else []
            if parts:
                candidate.franchise_index = ap.branch_franchise_index(card, parts)
            adaptations = [anime[str(i)] for i in ap.adaptation_ids(card) if str(i) in anime]
            if adaptations:
                ap.apply_adaptation(candidate, max(adaptations,
                    key=lambda c: ap.SongCandidate({}, c).own_index))
            # Never fabricate a level to make a reused question fit its old report.
            if candidate.level != row["level"]:
                continue
            frame = safe_name(row["frame"])
            stem = frame.rsplit("_frame", 1)[0]
            candidate.media_base = stem
            candidate.frame_name, candidate.frame_url = frame, row["page"]
            candidate.has_frame, candidate.source_link = True, row["chapter"]
            source = root / "frames" / frame
            if not source.is_file():
                continue
            shutil.copy2(source, Path(generator.folder) / "Images" / frame)
            for member in members:
                if member.startswith("Images/" + stem + "_poster."):
                    name = safe_name(member.split("/", 1)[1])
                    (Path(generator.folder) / "Images" / name).write_bytes(package.read(member))
                    candidate.poster_name, candidate.has_poster = name, True
                if member.startswith("Video/" + stem + " — появление "):
                    name = safe_name(member.split("/", 1)[1])
                    (Path(generator.folder) / "Video" / name).write_bytes(package.read(member))
                    candidate.entrance_frames[frame] = name
                    candidate.entrance_durations[name] = generator.s.entrance_seconds
            yield candidate


def restore(generator, roots):
    found = {}
    for name in roots:
        root = Path(name).resolve()
        source = prepared(generator, root) if (root / "prepared").is_dir() else archive(generator, root)
        for candidate in source:
            candidate._reserved = None
            candidate._bench_keys = _franchise_marks(candidate.anime, candidate.adapted_from)
            candidate._ready_media = (candidate.kind, candidate.music_effect)
            found[candidate.mal_id] = candidate
    values = sorted(found.values(), key=lambda c: (c.level, c.mal_id))
    if values:
        from si_hyx_parts.animepack.manga_editions import shares
        weights = shares(generator.s)
        target = generator.s.manga_level_avg or generator.s.level_avg or 6
        goals = {"manhwa": min(generator.s.manga_level_max, target + .75),
                 "manhua": min(generator.s.manga_level_max, target + 1.5)}
        goals["manga"] = max(generator.s.manga_level_min,
            (target * 100 - sum(weights[k] * value for k, value in goals.items()))
            / max(1, weights["manga"]))
        generator._manga_plan_stats = {"desired_levels": goals, "reused": len(values)}
        generator.log(f"Продолжение: {len(values)} готовых вопросов доступны без повторной загрузки.")
    return values
