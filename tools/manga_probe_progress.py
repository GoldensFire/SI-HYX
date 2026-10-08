"""Small accepted-question status snapshots for long diagnostic runs."""
from collections import Counter
import json


def callback(output, get_generator, log):
    previous = [-1]
    def progress(done, total, message):
        generator = get_generator()
        candidates = list(getattr(generator, "_selected_songs", ()))
        kinds = dict(Counter(c.anime.get("kind") for c in candidates))
        levels = [c.level for c in candidates]
        average = sum(levels) / len(levels) if levels else 0
        target = output / "status.json"
        temporary = target.with_suffix(".pending.json")
        temporary.write_text(json.dumps({"accepted": done, "total": total,
            "editions": kinds, "average": average, "stage": message},
            ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
        if done != previous[0] and done and (done % 5 == 0 or done == total):
            log(f"Готово {done}/{total}; состав {kinds}; средняя {average:.2f}.")
            previous[0] = done
    return progress
