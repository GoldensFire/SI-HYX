# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_pack. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


# ── Фабрики ──────────────────────────────────────────────────────────────────
def _pack(questions: str, *, ns: str = "", version: str = "5") -> str:
    xmlns = f' xmlns="{ns}"' if ns else ""
    return (f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<package name="Пак" version="{version}"{xmlns}>'
            '<rounds><round name="Раунд 1"><themes><theme name="Тема А">'
            f'<questions>{questions}</questions>'
            "</theme></themes></round></rounds></package>")

_pack.__module__ = _api.__name__
_api._pack = _pack

def _q5(price: int, answer: str = "Ответ", qtype: str = "",
        params: str = "", right: str = "") -> str:
    """Вопрос формата v5 (SIGame 7)."""
    attr = f' type="{qtype}"' if qtype else ""
    body = right or f"<right><answer>{answer}</answer></right>"
    return (f'<question price="{price}"{attr}><params>'
            '<param name="question" type="content"><item>Текст</item></param>'
            f"{params}</params>{body}</question>")

_q5.__module__ = _api.__name__
_api._q5 = _q5

def _q4(price: int, answer: str = "Ответ", qtype: str = "") -> str:
    """Вопрос формата v4 (тип — дочерним элементом)."""
    type_el = (f'<type name="{qtype}"><param name="theme">Тема кота</param>'
               f'<param name="price">300</param></type>') if qtype else ""
    return (f'<question price="{price}">{type_el}'
            "<scenario><atom>Текст</atom></scenario>"
            f"<right><answer>{answer}</answer></right></question>")

_q4.__module__ = _api.__name__
_api._q4 = _q4

def _siq(tmp_path, content: str, name: str = "pack.siq", media=None) -> str:
    path = tmp_path / name
    with _api.zipfile.ZipFile(path, "w") as zf:
        zf.writestr("content.xml", content)
        for arc, data in (media or {}).items():
            zf.writestr(arc, data, _api.zipfile.ZIP_STORED)
    return str(path)

_siq.__module__ = _api.__name__
_api._siq = _siq
