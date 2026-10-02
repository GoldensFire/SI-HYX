# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Готовые ролики появления и таймеры картинок в SIQ."""
import animepack as _api


def append_question(parent, candidate):
    names = ([candidate.entrance_video] if candidate.entrance_video else
             [candidate.entrance_frames[name] for name in candidate.question_frames
              if name in candidate.entrance_frames])
    for name in names:
        video = _api.ET.SubElement(parent, "item", {
            "type": "video", "isRef": "True",
            "duration": _api.fmt_duration(4 if candidate.is_character else 5)})
        video.text = name
    return bool(names)


def append_image(parent, candidate, name, seconds=None):
    video = candidate.entrance_frames.get(name)
    attrs = {"type": "video" if video else "image", "isRef": "True"}
    if seconds is not None:
        attrs["duration"] = _api.fmt_duration(seconds)
    image = _api.ET.SubElement(parent, "item", attrs)
    image.text = video or name
