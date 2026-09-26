# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""main. Public namespace: edit_tab."""
import edit_tab as _api


# ─── Standalone test entry point ───────────────────────────────────────────────
def main():
    app = _api.QApplication(_api.sys.argv)
    app.setApplicationName("SI-HYX — Монтаж")
    app.setStyle("Fusion")
    w = _api.EditTab()
    w.resize(1400, 900)
    w.show()
    _api.sys.exit(app.exec())

main.__module__ = _api.__name__
_api.main = main
