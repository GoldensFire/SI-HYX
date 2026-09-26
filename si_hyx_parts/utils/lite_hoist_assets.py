# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_lite_hoist_assets. Public namespace: utils."""
import utils as _api


def _lite_hoist_assets(code: str, assets: list) -> str:
    """Выносит крупные ассет-литералы из инлайн-скрипта в общий список assets,
    заменяя каждый на глобальную ссылку __SI_Ak (k = индекс в assets). Возвращает
    slimmed-код скрипта. Сами ассеты кладутся в data-si один раз (без повторного
    base64), а loader объявляет их как window.__SI_Ak до запуска скриптов."""
    def _repl(m):
        tok = m.group(0)
        if tok[0] in "\"'":                          # строковый литерал (не комментарий)
            inner = tok[1:-1]
            if len(inner) >= _api._LITE_HOIST_MIN and _api._LITE_ASSET_INNER_RX.fullmatch(inner):
                idx = len(assets)
                assets.append(inner)                 # исходное значение (сырой b64 / data:)
                return "__SI_A%d" % idx
        return tok                                   # комментарии и обычные строки — как есть
    # _LITE_STRIP_RX матчит комментарии и строковые литералы целиком, поэтому не
    # заденем base64 внутри комментария или вложенные кавычки.
    return _api._LITE_STRIP_RX.sub(_repl, code)

_lite_hoist_assets.__module__ = _api.__name__
_api._lite_hoist_assets = _lite_hoist_assets
