# -*- coding: utf-8 -*-
"""Открытие SIQ из списка и найденного вопроса."""
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from si_hyx_parts.animepack_tab import pack_list_dialog as ui


def test_double_click_opens_the_pack_file_from_both_lists(qapp, tmp_path, monkeypatch):
    path = tmp_path / "пак с пробелами.siq"
    path.write_bytes(b"pack")
    opened = []
    monkeypatch.setattr(ui.QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    dialog = ui.IncludedPacksDialog("Паки", [str(path)], str(tmp_path), search_questions=True)
    try:
        item = QListWidgetItem("вопрос")
        item.setData(Qt.ItemDataRole.UserRole, {"path": str(path)})
        dialog.results.addItem(item)
        dialog.list.itemDoubleClicked.emit(dialog.list.item(0))
        dialog.results.itemDoubleClicked.emit(item)
        assert [Path(url.toLocalFile()) for url in opened] == [path, path]
        assert all(url.isLocalFile() for url in opened)
    finally:
        dialog.close()


def test_right_click_opens_the_clicked_pack_and_preserves_reveal(qapp, tmp_path, monkeypatch):
    paths = [tmp_path / "first.siq", tmp_path / "second.siq"]
    for path in paths:
        path.write_bytes(b"pack")
    opened, revealed = [], []
    monkeypatch.setattr(ui.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    monkeypatch.setattr(ui, "reveal_in_explorer", revealed.append)
    dialog = ui.IncludedPacksDialog("Паки", [str(p) for p in paths], str(tmp_path))
    try:
        dialog.list.setCurrentRow(0)
        menu = dialog._item_menu(dialog.list, dialog.list.item(1))
        assert [a.text() for a in menu.actions()] == ["Открыть пак", "Показать в папке"]
        menu.actions()[0].trigger()
        menu.actions()[1].trigger()
        assert [Path(value) for value in opened] == [paths[1]]
        assert revealed == [str(paths[1])]
        assert dialog.list.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
        missing = QListWidgetItem("missing")
        missing.setData(Qt.ItemDataRole.UserRole, str(tmp_path / "missing.siq"))
        assert not dialog._item_menu(dialog.list, missing).actions()[0].isEnabled()
        dialog._open(missing)
        assert [Path(value) for value in opened] == [paths[1]]
    finally:
        dialog.close()
