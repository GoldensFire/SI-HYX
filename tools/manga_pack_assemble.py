"""Select a balanced complete pack from this run's already prepared questions."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import animepack as ap
from config import SETTINGS_FILE
from manga_prepared import restore
from manga_pack_probe import contact_sheets
from si_hyx_parts.animepack.manga_editions import edition


def choices(candidates, quota):
    """One witness for each achievable sum of exactly quota whole questions."""
    groups = defaultdict(list)
    for candidate in candidates:
        groups[int(candidate.level)].append(candidate)
    levels = sorted(groups)
    states = {(0, 0): ()}
    for level in levels:
        following = {}
        for (count, points), witness in states.items():
            for take in range(min(len(groups[level]), quota - count) + 1):
                key = count + take, points + take * level
                following.setdefault(key, witness + (take,))
        states = following
    output = {}
    for (count, points), witness in states.items():
        if count == quota:
            output[points] = [candidate for level, take in zip(levels, witness)
                              for candidate in groups[level][:take]]
    return output


def balanced(candidates, settings):
    quotas = ap.MangaMix(settings, settings.total_questions).kind_target
    need = {"manga": quotas[""], "manhwa": quotas["manhwa"], "manhua": quotas["manhua"]}
    pools = {kind: [c for c in candidates if edition(c.anime) == kind]
             for kind in need}
    occupied, groups = set(), {}
    for kind in sorted(need, key=lambda k: len(pools[k]) / max(1, need[k])):
        group = []
        for candidate in sorted(pools[kind], key=lambda c: (c.level, c.mal_id)):
            marks = set(getattr(candidate, "_bench_keys", ()) or ())
            if marks & occupied:
                continue
            occupied.update(marks)
            group.append(candidate)
        groups[kind] = group
    plans = {kind: choices(group, need[kind]) for kind, group in groups.items()}
    missing = {kind: need[kind] - len(groups[kind]) for kind in need
               if len(groups[kind]) < need[kind]}
    if missing:
        raise RuntimeError(f"Нужно подготовить ещё вопросы: {missing}")
    combinations = {}
    for first, first_rows in plans["manhwa"].items():
        for second, second_rows in plans["manhua"].items():
            combinations.setdefault(first + second, first_rows + second_rows)
    target = (settings.manga_level_avg or settings.level_avg) * settings.total_questions
    best = min(((abs(first + second - target), first + second, rows + other)
                for first, rows in plans["manga"].items()
                for second, other in combinations.items()), key=lambda row: row[:2])
    if best[0] > settings.manga_average_tolerance * settings.total_questions + 1e-9:
        raise RuntimeError(f"Подготовленные вопросы дают ближайшую среднюю "
                           f"{best[1] / settings.total_questions:.2f}; нужны замены.")
    return best[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source", action="append", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "frames").mkdir(exist_ok=True)
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    settings = ap.PackSettings.from_dict(profile)
    saved = json.loads(Path(SETTINGS_FILE).read_text(encoding="utf-8"))
    settings.gemini_key = str(saved.get("api_keys", {}).get("gemini") or "")
    generator = ap.AnimePackGenerator(settings)
    ap.install_favorites_norms(generator.db_cache)
    generator.prepare_dirs()
    try:
        candidates = restore(generator, args.source)
        selected = balanced(candidates, settings)
        result = ap.PackResult(requested=settings.total_questions)
        generator.assemble(selected, str(output / f"{settings.title}.siq"), result)
        rows = []
        for candidate in selected:
            shutil.copy2(Path(generator.folder) / "Images" / candidate.frame_file,
                         output / "frames" / candidate.frame_file)
            rows.append({"title": candidate.title_ru, "mal": candidate.mal_id,
                "level": candidate.level, "kind": candidate.anime.get("kind"),
                "frame": candidate.frame_file, "page": candidate.frame_url,
                "chapter": candidate.source_link,
                "franchise_keys": list(getattr(candidate, "_bench_keys", ()) or ())})
        report = {"pack": result.path, "requested": settings.total_questions,
                  "made": len(rows), "cancelled": False, "seconds": 0,
                  "questions": rows, "assembled_from_prepared": args.source}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "settings.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "generation.log").write_text("\n".join(
            (Path(source) / "generation.log").read_text(encoding="utf-8")
            for source in args.source if (Path(source) / "generation.log").exists()), encoding="utf-8")
        contact_sheets(rows, output)
        print(f"Assembled {len(rows)} questions; mean {sum(c.level for c in selected) / len(selected):.3f}")
    finally:
        generator.cleanup()


if __name__ == "__main__":
    main()
