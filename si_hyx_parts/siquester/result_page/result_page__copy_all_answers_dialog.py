# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ResultPage: _copy_all_answers_dialog. Public namespace: siquester.result_page."""
import siquester.result_page as _api


def _copy_all_answers_dialog(self, datasets: list):
    """Show package selection dialog, then copy answers from chosen packages."""
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QScrollArea

    dlg = QDialog(self)
    dlg.setWindowTitle("📝 Выбрать пакеты для копирования ответов")
    dlg.setMinimumWidth(420)
    dlg.setMinimumHeight(360)
    dlg.setStyleSheet("QDialog{background:#181825;color:#cdd6f4;}")

    vl = QVBoxLayout(dlg); vl.setContentsMargins(16,14,16,14); vl.setSpacing(8)
    vl.addWidget(_api._lbl("Выберите пакеты:", "color:#cdd6f4;font-size:12px;font-weight:700;"))

    scroll = QScrollArea(); scroll.setWidgetResizable(True)
    scroll.setStyleSheet("border:1px solid #45475a;border-radius:4px;background:#1e1e2e;")
    inner = _api.QWidget(); inner.setStyleSheet(_api._SS_TRANSPARENT)
    il = QVBoxLayout(inner); il.setContentsMargins(8,8,8,8); il.setSpacing(4)
    scroll.setWidget(inner)
    vl.addWidget(scroll, stretch=1)

    _checkboxes: list = []
    for ds in datasets:
        pkg = ds.get("pkg_name","?")
        w = ds.get("widget")
        siq = getattr(w, "_siq", None) if w else None
        cb = _api.QCheckBox(pkg)
        cb.setChecked(True)
        cb.setStyleSheet(
            "QCheckBox{color:#cdd6f4;font-size:12px;}"
            "QCheckBox::indicator{width:14px;height:14px;border:1px solid #45475a;"
            "border-radius:3px;background:#1e1e2e;}"
            "QCheckBox::indicator:checked{background:#89b4fa;border-color:#89b4fa;}")
        il.addWidget(cb)
        _checkboxes.append((cb, ds, siq))

    bot = QHBoxLayout(); bot.addStretch()
    sel_all = _api.AnimatedButton("✓ Все"); sel_all.setObjectName(_api._ON_BTN_SORT); sel_all.setFixedHeight(24)
    sel_none = _api.AnimatedButton("✗ Ни одного"); sel_none.setObjectName(_api._ON_BTN_SORT); sel_none.setFixedHeight(24)
    sel_all.clicked.connect(lambda: [cb.setChecked(True) for cb,_,__ in _checkboxes])
    sel_none.clicked.connect(lambda: [cb.setChecked(False) for cb,_,__ in _checkboxes])
    cancel_btn = _api.AnimatedButton("Отмена"); cancel_btn.clicked.connect(dlg.reject)
    ok_btn = _api.AnimatedButton("📋 Копировать"); ok_btn.setObjectName(_api._ON_BTN_ANALYZE)
    ok_btn.clicked.connect(dlg.accept)
    bot.addWidget(sel_all); bot.addWidget(sel_none); bot.addWidget(cancel_btn); bot.addWidget(ok_btn)
    vl.addLayout(bot)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    chosen = [(ds, siq) for cb, ds, siq in _checkboxes if cb.isChecked()]
    if not chosen:
        return

    def _is_filename(s: str) -> bool:
        return _api.Path(s.strip()).suffix.lower() in _api._MEDIA_EXTS

    def _collect_texts(items, param):
        return [it["text"].strip() for it in items
                if it.get("param") == param
                and it.get("type") == "text"
                and not it.get("is_ref")
                and it.get("text","").strip()]

    all_lines = []
    for ds, siq in chosen:
        pkg_name = ds.get("pkg_name","Пакет")
        all_lines.append(f"=== {pkg_name} ===")
        all_lines.append("")
        rounds_src = siq.rounds if siq else []
        for rd in rounds_src:
            all_lines.append(f"[{rd['name']}]")
            for th in rd["themes"]:
                for q in th["questions"]:
                    q_type = q.get("q_type","")
                    # Skip point-on-image answers
                    if q_type == "point":
                        continue
                    items = q.get("items",[])

                    if q_type == "select":
                        # Include select-type answer options text
                        opts = q.get("answer_options",{})
                        correct_keys = set(q.get("answers",[]))
                        parts = []
                        for k in sorted(opts.keys()):
                            opt_items = opts[k]
                            for oi in opt_items:
                                if oi.get("type")=="text" and not oi.get("is_ref") and oi.get("text","").strip():
                                    mark = "✓" if k in correct_keys else ""
                                    parts.append(f"{k}{mark}: {oi['text'].strip()}")
                        if parts:
                            all_lines.append("📋 " + " | ".join(parts))
                    else:
                        right_raw = [a.strip() for a in q.get("answers",[]) if a.strip()]
                        right = [a for a in right_raw if not _is_filename(a)]
                        ans_param_texts = _collect_texts(items, "answer")
                        for t in ans_param_texts:
                            if t not in right:
                                right.append(t)
                        if right:
                            all_lines.append("✅ " + " | ".join(right))
                all_lines.append("")
        all_lines.append("")

    _api.QApplication.clipboard().setText("\n".join(all_lines))
    mw = self._mw_ref
    if hasattr(mw, "_show_save_notification"):
        mw._save_notif.setText("📋  Ответы скопированы")
        mw._show_save_notification()
        _api._notif_reset(mw)

def _save_siq_inplace(self):
    """SIQ is already auto-saved on every edit; show notification and refresh date."""
    src = self.ds.get("siq_path", "")
    if not src or not _api.os.path.exists(src):
        _api.msgbox_warning(self, "Нет файла", "SIQ-файл не найден или не прикреплён.")
        return
    mw = self._mw_ref
    if hasattr(mw, '_show_save_notification'):
        mw._show_save_notification()
    self._refresh_banner_widget()   # pick up the current on-disk package size
    # Refresh the "saved: dd.mm.yyyy HH:MM" label in the toolbar
    if hasattr(mw, '_set_filename_text'):
        try:
            mtime = _api.os.path.getmtime(src)
            dt = _api._dt.datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M")
            mw._set_filename_text(f"📄 {_api.os.path.basename(src)}  · сохранён {dt}")
        except Exception:
            pass
