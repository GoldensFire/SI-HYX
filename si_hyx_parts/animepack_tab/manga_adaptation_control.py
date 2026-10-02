# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Ползунок доли экранизованной манги: «Любое» и 0…100%."""
from .difficulty_slider import DifficultySlider


class AdaptationPercent(DifficultySlider):
    def __init__(self, parent=None):
        super().__init__(-1, 100, 50, parent)
        self.setSpecialValueText("Любое")
        self.setSuffix(" %")

    def text(self):
        return self.number.text()
