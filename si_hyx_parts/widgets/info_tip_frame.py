# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Tooltip source checks: is the hovered owner still the one the tip belongs to."""

from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication


def source_is_current(owner, point=None, region=None):
    """Reject late help events, including another cell in the same viewport."""
    if QApplication.activePopupWidget() is not None:
        return False
    cursor = QCursor.pos()
    if region is None and point is not None and cursor != point:
        return False
    try:
        if not owner.isVisible():
            return False
        if region is not None:
            # A one-pixel move can cross a cell or icon boundary. Validate the
            # semantic area, not a distance tolerance from the old event.
            if not region.contains(owner.mapFromGlobal(cursor)):
                return False
            if point is not None and not region.contains(owner.mapFromGlobal(point)):
                return False
        current = QApplication.widgetAt(cursor)
        while current is not None:
            if current is owner:
                return True
            # A child's own tip takes precedence over its container's tip.
            if current.property("infoTipText") or current.toolTip():
                return False
            current = current.parentWidget()
    except RuntimeError:  # The source was deleted while an event was queued.
        pass
    return False
