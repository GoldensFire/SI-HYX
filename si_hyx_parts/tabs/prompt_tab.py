# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PromptTab. Public namespace: tabs."""
import tabs as _api


class PromptTab(_api.QWidget):
    """Вкладка с промптами из произвольного .txt файла, выбранного пользователем.
    Последний выбранный файл запоминается в настройках и подгружается при старте."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checkboxes = []  # list of QCheckBox, each has ._full_text attribute
        # Последний выбранный файл (любой .txt) — из настроек; по умолчанию пусто.
        try:
            self._prompt_path = _api.load_settings().get("prompt_file", "") or ""
        except Exception:
            self._prompt_path = ""
        self._build_ui()
        self._load_prompts()

    def _build_ui(self):
        root = _api.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top = _api.QHBoxLayout()
        lbl = _api.QLabel("Промпты для SiGame-игр:")
        lbl.setStyleSheet("font-weight:bold; color:#89b4fa; font-size:14px;")
        top.addWidget(lbl)
        top.addStretch()

        btn_all = _api._icon_btn("Все", 'fa5s.check')
        btn_all.setFixedWidth(72)
        btn_all.clicked.connect(self._select_all)
        btn_none = _api._icon_btn("Снять", 'fa5s.times')
        btn_none.setFixedWidth(72)
        btn_none.clicked.connect(self._select_none)
        self.btn_copy_sel = _api._icon_btn("Копировать выбранные", 'fa5s.copy')
        self.btn_copy_sel.clicked.connect(self._copy_selected)
        btn_pick = _api._icon_btn("Выбрать файл", 'fa5s.folder-open')
        btn_pick.setToolTip("Загрузить промпты из любого .txt файла")
        btn_pick.clicked.connect(self._choose_prompt_file)
        btn_reload = _api._icon_btn("Обновить", 'fa5s.sync-alt')
        btn_reload.clicked.connect(self._load_prompts)

        top.addWidget(btn_all)
        top.addWidget(btn_none)
        top.addWidget(self.btn_copy_sel)
        top.addWidget(btn_pick)
        top.addWidget(btn_reload)
        root.addLayout(top)

        scroll = _api.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cb_widget = _api.QWidget()
        self._cb_layout = _api.QVBoxLayout(self._cb_widget)
        self._cb_layout.setContentsMargins(4, 4, 4, 4)
        self._cb_layout.setSpacing(2)

        # Подсказка на пустом поле — как пользоваться вкладкой.
        self._empty_hint = _api.QLabel(
            "Как это работает\n\n"
            "• Нажмите «Выбрать файл» и укажите любой .txt с промптами.\n"
            "   Выбранный файл запоминается и подгружается при следующем запуске.\n"
            "• Каждый пункт, начинающийся с «1)», «2)», «3)» … — отдельный промпт.\n"
            "   Файл без такой нумерации показывается одним цельным промптом.\n"
            "• Отметьте нужные галочками и нажмите «Копировать выбранные» —\n"
            "   они скопируются в буфер обмена (через пустую строку между собой).\n"
            "• «Обновить» — перечитать файл, если вы его изменили.\n\n"
            "Сейчас файл не выбран — нажмите «Выбрать файл».")
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet("color:#9399b2; font-size:12px; padding:8px 4px;")
        self._empty_hint.setAlignment(_api.Qt.AlignmentFlag.AlignTop | _api.Qt.AlignmentFlag.AlignLeft)
        self._cb_layout.addWidget(self._empty_hint)

        self._cb_layout.addStretch()
        scroll.setWidget(self._cb_widget)
        root.addWidget(scroll)

        self._status = _api.QLabel("")
        self._status.setStyleSheet("color:#585b70; font-size:11px;")
        root.addWidget(self._status)

    def _load_prompts(self):
        # Удаляем только сами чекбоксы — подсказка _empty_hint и stretch остаются.
        for cb in self._checkboxes:
            self._cb_layout.removeWidget(cb)
            cb.deleteLater()
        self._checkboxes.clear()

        if not self._prompt_path:
            self._status.setText("Файл не выбран — нажмите «Выбрать файл»")
            self._empty_hint.setVisible(True)
            return
        if not _api.os.path.exists(self._prompt_path):
            self._status.setText(f"Файл не найден: {self._prompt_path}")
            self._empty_hint.setVisible(True)
            return
        try:
            with open(self._prompt_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self._status.setText(f"Ошибка чтения: {e}")
            self._empty_hint.setVisible(True)
            return

        sections = self._parse_sections(content)
        # Файл без нумерованных секций (N)) — показываем как один цельный промпт
        if not sections and content.strip():
            sections = [(_api.os.path.basename(self._prompt_path), content.strip())]

        # Чекбоксы вставляем перед stretch (последний элемент), но после подсказки.
        for title, body in sections:
            cb = _api.QCheckBox(title)
            cb.setStyleSheet("font-size:13px; padding:5px 2px;")
            cb._full_text = title + "\n" + body  # type: ignore[attr-defined]
            self._checkboxes.append(cb)
            self._cb_layout.insertWidget(self._cb_layout.count() - 1, cb)

        # Подсказку показываем, только когда промптов нет.
        self._empty_hint.setVisible(not self._checkboxes)
        self._status.setText(f"{len(self._checkboxes)} промптов  ·  {_api.os.path.basename(self._prompt_path)}")

    def _choose_prompt_file(self):
        start_dir = _api.os.path.dirname(self._prompt_path) if self._prompt_path else ""
        path, _ = _api.QFileDialog.getOpenFileName(
            self, "Выбрать файл с промптами", start_dir,
            "Текстовые файлы (*.txt);;Все файлы (*.*)")
        if path:
            self._prompt_path = path
            # Запоминаем выбор в общих настройках (merge, чтобы не затереть прочее).
            # Пустой словарь тут значит «настройки не прочитались» (файл занят/
            # битый — load_settings молча отдаёт {}): дописать в него один ключ и
            # сохранить — значит затереть ВСЕ остальные настройки одиноким
            # prompt_file. Тогда пропускаем запись, как и _persist_priority.
            try:
                s = _api.load_settings()
                if isinstance(s, dict) and s:
                    s["prompt_file"] = path
                    _api.save_settings(s)
            except Exception:
                pass
            self._load_prompts()

    def _parse_sections(self, text):
        sections = []
        current_title = None
        current_lines = []
        for line in text.splitlines():
            if _api.re.match(r'^\d+\)', line.strip()):
                if current_title is not None:
                    sections.append((current_title, "\n".join(current_lines).strip()))
                current_title = line.strip()
                current_lines = []
            else:
                if current_title is not None:
                    current_lines.append(line)
        if current_title is not None:
            sections.append((current_title, "\n".join(current_lines).strip()))
        return sections

    def _select_all(self):
        for cb in self._checkboxes:
            cb.setChecked(True)

    def _select_none(self):
        for cb in self._checkboxes:
            cb.setChecked(False)

    def _copy_selected(self):
        parts = [cb._full_text for cb in self._checkboxes if cb.isChecked()]  # type: ignore[attr-defined]
        if not parts:
            self._status.setText("Ничего не выбрано")
            return
        _api.QApplication.clipboard().setText("\n\n".join(parts))
        n = len(parts)
        suffix = "а" if n in (2, 3, 4) else "ов" if n != 1 else ""
        orig = self.btn_copy_sel.text()
        self.btn_copy_sel.setText(f"Скопировано {n} пункт{suffix}!")
        _api.QTimer.singleShot(2000, lambda: self.btn_copy_sel.setText(orig))
        self._status.setText(f"Скопировано {n} пункт{suffix} в буфер")

PromptTab.__module__ = _api.__name__
_api.PromptTab = PromptTab
