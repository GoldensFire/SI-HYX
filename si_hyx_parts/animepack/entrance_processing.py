# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Применяет появление к выбранным составам и публикует только готовые файлы."""
from pathlib import Path

from image_entrance import EFFECT_LABELS, choose_effect
from .entrance_encoding import encode_image, encode_video
from .generation_diagnostics import operation


@operation("появление картинки")
def apply(generator, candidate):
    settings = generator.s
    if not settings.entrance_enabled or candidate.kind not in settings.entrance_targets:
        return True
    # Ролик песни может заменитьcя аудио; у него уже нет картинки вопроса.
    if not candidate.has_video and not candidate.question_frames:
        return True
    effect = choose_effect(settings, generator.rng)
    seed = generator.rng.getrandbits(64)
    created = []
    images, durations, video_name = {}, {}, ""
    root = Path(generator.folder)
    try:
        if candidate.has_video:
            video_name = Path(candidate.video_out).stem + " — появление.mp4"
            output = root / "Video" / video_name
            created.append(output)
            encode_video(generator, root / "Video" / candidate.video_out,
                         output, effect, seed)
        else:
            seconds = settings.entrance_seconds
            if candidate.is_studio:
                from .studio_question import frame_seconds
                # Время появления входит в прежнюю длительность каждого кадра.
                seconds = min(seconds, max(0.2, frame_seconds(settings) - 0.2))
            for index, name in enumerate(candidate.question_frames):
                target = f"{Path(candidate.video_out).stem} — появление {index + 1}.mp4"
                output = root / "Video" / target
                created.append(output)
                duration = encode_image(generator, root / "Images" / name,
                                        output, effect, seed + index, seconds)
                images[name], durations[target] = target, duration
        if generator.stopped():
            raise RuntimeError("остановлено")
    except Exception as exc:  # noqa: BLE001 — вопрос заменяется следующим кандидатом
        for path in created:
            path.unlink(missing_ok=True)
        if not generator.stopped():
            generator.log(f"Появление «{candidate.title_ru}» не собралось: {exc}")
        return False
    candidate.entrance_effect = effect
    candidate.entrance_frames = images
    candidate.entrance_durations = durations
    candidate.entrance_video = video_name
    generator.log(f"«{candidate.title_ru}»: появление — {EFFECT_LABELS[effect]}")
    return True
