# -*- coding: utf-8 -*-
"""Save metadata once per selection, after its producers have stopped."""


def checkpoint(generator):
    # A franchise/API batch changes a few records in a ~400 MB database.
    # Rewriting the whole database for each batch stalls candidate discovery.
    if not getattr(generator, "_defer_cache_writes", False):
        return generator.db_cache.save()
    return False
