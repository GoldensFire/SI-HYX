"""Choose an uninterrupted confirmed verse without inventing missing lyric times."""


def candidates(rows, minimum_duration):
    runs, current = [], []
    for row in rows:
        if current and (row["line_index"] != current[-1]["line_index"] + 1
                        or row["start"] - current[-1]["end"] > 3):
            runs.append(current)
            current = []
        current.append(row)
    if current:
        runs.append(current)
    valid = [run for run in runs if len(run) >= 3
             and run[-1]["end"] - run[0]["start"] >= minimum_duration + .2]
    return sorted(valid, key=lambda run: run[-1]["end"] - run[0]["start"], reverse=True)


def select(rows, minimum_duration):
    valid = candidates(rows, minimum_duration)
    return valid[0] if valid else []
