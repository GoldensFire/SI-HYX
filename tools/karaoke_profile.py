"""Save measured wall spans; overlapping waits must not be added to model work."""
import json
import os
from pathlib import Path
import time

from karaoke.asr_worker import cpu_threads


def save(generator, output, started):
    total = time.monotonic() - started
    stages = []
    with generator._stage_lock:
        spans = {name: list(rows) for name, rows in generator._stage_spans.items()}
    for name, rows in spans.items():
        wall = generator._merge_spans(rows)
        stages.append({'name': name, 'wall_seconds': wall,
                       'worker_seconds': sum(b - a for a, b in rows),
                       'percent_of_generation': 100 * wall / max(.001, total),
                       'calls': len(rows)})
    stages.sort(key=lambda row: row['wall_seconds'], reverse=True)
    events = sorted((point, delta) for a, b in spans.get('аудио', [])
                    for point, delta in ((a, 1), (b, -1)))
    active = peak = 0
    for _, delta in events:
        active += delta
        peak = max(peak, active)
    payload = {'generation_seconds': total, 'spans_overlap': True,
               'stages': stages, 'requested_workers': generator.s.parallel,
               'peak_audio_tasks': peak,
               'ml_threads': os.environ.get('SI_HYX_ML_THREADS', '4'),
               'separator_threads': cpu_threads(12),
               'recognition_threads': cpu_threads()}
    Path(output, 'timing-profile.json').write_text(json.dumps(payload, ensure_ascii=False,
                                                            indent=2), encoding='utf-8')
    return payload
