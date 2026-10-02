# -*- coding: utf-8 -*-
"""Бронь только показанных и сейчас загружаемых тайтлов вопроса-студии."""
from .studio_question import _pack_marks


def reserve_card(generator, candidate, card) -> bool:
    primary = set(getattr(candidate, "_reserved", ()) or ())
    marks = _pack_marks(card) - primary
    with generator._studio_lock:
        own = set(getattr(candidate, "_studio_reserved_franchises", ()))
        if (not generator.s.dup_franchise
                and marks & (generator._used_franchise - own)):
            return False
        generator._used_franchise.update(marks)
        candidate._studio_reserved_franchises = tuple(own | marks)
    return True


def release_card(generator, candidate, card) -> None:
    primary = set(getattr(candidate, "_reserved", ()) or ())
    with generator._studio_lock:
        own = set(getattr(candidate, "_studio_reserved_franchises", ()))
        marks = (_pack_marks(card) - primary) & own
        generator._used_franchise.difference_update(marks)
        candidate._studio_reserved_franchises = tuple(own - marks)


def retain_cards(generator, candidate, cards) -> None:
    """После успеха убирает даже бронь исходного тайтла, если кадра не было."""
    shown = set().union(*(_pack_marks(card) for card in cards))
    with generator._studio_lock:
        primary = set(getattr(candidate, "_reserved", ()) or ())
        extra = set(getattr(candidate, "_studio_reserved_franchises", ()))
        generator._used_franchise.difference_update((primary | extra) - shown)
        candidate._reserved = tuple(primary & shown)
        candidate._studio_reserved_franchises = tuple(shown - primary)
