# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MediaTab: ctx. Public namespace: tabs."""
import tabs as _api


def ctx(self, pos):
    m = _api.QMenu()
    sel = self.tree.itemAt(pos)
    if sel:
        iid = sel.data(0, _api.Qt.ItemDataRole.UserRole)
        entry = self._item_data_map.get(iid, {})
        out_path = entry.get('out_path', '')
        if out_path and _api.os.path.exists(out_path):
            m.addAction(_api.get_icon('fa5s.play'), "Открыть файл", lambda checked=False, p=out_path: self.open_output_file(p))
        m.addAction(_api.get_icon('fa5s.folder-open'), "Перейти к файлу", lambda checked=False, it=sel: self.open_file_location(it))
        m.addAction(_api.get_icon('fa5s.undo'), "Сбросить статус", lambda checked=False: self.reset_status())
        m.addSeparator()
        m.addAction(_api.get_icon('fa5s.times'), "Удалить", lambda checked=False: self.rem())
    m.addAction(_api.get_icon('fa5s.paste'), "Вставить файлы", lambda checked=False: self.paste_files())
    m.addAction(_api.get_icon('fa5s.trash'), "Очистить всё", lambda checked=False: self.clear())
    m.exec(self.tree.mapToGlobal(pos))

def open_file_location(self, item):
    try:
        path = item.toolTip(0) or item.data(0, _api.Qt.ItemDataRole.ToolTipRole)
        if not path: return
        from utils import reveal_in_explorer
        reveal_in_explorer(path)
    except Exception as e:
        self.main.log(f"open_file_location error: {e}")

def paste_files(self):
    try:
        mime = _api.QApplication.clipboard().mimeData()
        if mime.hasUrls():
            self.add_paths([u.toLocalFile() for u in mime.urls() if u.toLocalFile()])
    except Exception as e:
        self.main.log(f"paste_files error: {e}")
