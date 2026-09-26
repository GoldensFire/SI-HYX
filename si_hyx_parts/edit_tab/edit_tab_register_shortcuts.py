# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: register_shortcuts. Public namespace: edit_tab."""
import edit_tab as _api


# ── Shortcuts ─────────────────────────────────────────────────────────
def register_shortcuts(self):
    # Контекст WidgetWithChildren: хоткеи работают только когда вкладка
    # «Монтаж» в фокусе — не перехватывают Space/I/O на других вкладках.
    ctx = _api.Qt.ShortcutContext.WidgetWithChildrenShortcut

    def add_shortcut(seq, handler):
        act = _api.QAction(self)
        act.setShortcut(_api.QKeySequence(seq))
        act.setShortcutContext(ctx)
        act.triggered.connect(handler)
        self.addAction(act)

    try:
        add_shortcut(_api.Qt.Key.Key_Space, self.toggle_play)
        add_shortcut(_api.Qt.Key.Key_Left,  _api.partial(self.step_frame_scrub, -1))
        add_shortcut(_api.Qt.Key.Key_Right, _api.partial(self.step_frame_scrub,  1))
        # F/I/O/WASD/Ctrl+S НЕ регистрируем через QKeySequence-строку — на
        # кириллической раскладке физическая клавиша шлёт Qt переведённый
        # код кириллической буквы (Ф/Ш/Щ/Ц/Ы/В/Ы), а не Key_F/I/O/A/S/D/W,
        # и такой QShortcut на ней молча не срабатывает вовсе (та же
        # природа бага, что и с Ctrl+Z/Ctrl+Y — см. keyPressEvent ниже и
        # _pan_dir_from_event в tabs.py). Обрабатываем их там же, через
        # nativeVirtualKey — независимо от раскладки.
        # Обрезка до точки воспроизведения (настраиваемые сочетания) —
        # храним QShortcut, чтобы можно было переназначить в Настройках.
        self._sc_trim_start = _api.QShortcut(_api.QKeySequence(self.trim_start_seq), self)
        self._sc_trim_start.setContext(ctx)
        self._sc_trim_start.activated.connect(self.trim_start_to_playhead)
        self._sc_trim_end = _api.QShortcut(_api.QKeySequence(self.trim_end_seq), self)
        self._sc_trim_end.setContext(ctx)
        self._sc_trim_end.activated.connect(self.trim_end_to_playhead)
        # Undo/redo: ВСЕ сочетания вешаем на ОДНО действие каждого типа через
        # setShortcuts([...]). Раньше StandardKey.Redo и явный "Ctrl+Y" были
        # ДВУМЯ разными QAction с одинаковым сочетанием (на Windows
        # StandardKey.Redo == Ctrl+Y) — Qt считал это «неоднозначным
        # сочетанием» и не срабатывал НИ ОДИН из них: Ctrl+Z работал, а
        # Ctrl+Y — нет. Один QAction с несколькими сочетаниями неоднозначности
        # не создаёт (после дедупликации ниже).
        #
        # РАСКЛАДОЧНЫЕ ЛИТЕРАЛЫ "Ctrl+Я"/"Ctrl+Н" (рус. Я=Z, Н=Y по месту
        # клавиши) СЮДА НЕ ДОБАВЛЯЕМ — повторный баг-репорт ("Ambiguous
        # shortcut overload: Ctrl+Z"/"Ctrl+?") показал, что именно они и
        # ЛОМАЮТ act_undo/act_redo: физическое нажатие Ctrl+Z на кириллице
        # Qt внутренне сопоставляет С ОБОИМИ кандидатами сразу (и с
        # "Ctrl+Z" через ASCII-фолбэк Windows для Ctrl+буква, и с
        # "Ctrl+Я"/"Ctrl+Н" через переведённый раскладкой символ) — два
        # разных QKeySequence в списке ОДНОГО QAction, оба совпавшие с
        # одним и тем же событием, Qt тоже считает неоднозначностью и не
        # срабатывает вообще. Кириллицу целиком закрывает keyPressEvent
        # ниже через nativeVirtualKey (не зависит от раскладки в принципе).
        def _dedup_seqs(seqs):
            seen = set(); out = []
            for s in seqs:
                key = s.toString()
                if key and key not in seen:
                    seen.add(key); out.append(s)
            return out

        act_undo = _api.QAction(self)
        act_undo.setShortcuts(_dedup_seqs([_api.QKeySequence(_api.QKeySequence.StandardKey.Undo),
                               _api.QKeySequence("Ctrl+Z")]))
        act_undo.setShortcutContext(ctx)
        act_undo.triggered.connect(self.undo)
        self.addAction(act_undo)
        act_redo = _api.QAction(self)
        act_redo.setShortcuts(_dedup_seqs([_api.QKeySequence(_api.QKeySequence.StandardKey.Redo),
                               _api.QKeySequence("Ctrl+Y"), _api.QKeySequence("Ctrl+Shift+Z")]))
        act_redo.setShortcutContext(ctx)
        act_redo.triggered.connect(self.redo)
        self.addAction(act_redo)
        # Раньше тут ещё висела «подстраховка» — те же Ctrl+Z/Ctrl+Y вторым
        # QShortcut'ом WidgetShortcut прямо на self.waveform (на случай, если
        # после перетаскивания маркеров IN/OUT фокус остаётся на волне, а
        # WidgetWithChildrenShortcut выше по дереву почему-то не срабатывает).
        # На самом деле причиной был дубль сочетания ВНУТРИ act_undo/act_redo
        # (см. выше) — Qt считал его неоднозначным и не срабатывал act_undo/
        # act_redo вообще, независимо от фокуса. После дедупликации
        # WidgetWithChildrenShortcut сам покрывает фокус на волне (она —
        # дочерний виджет self), а второй QShortcut с тем же сочетанием на
        # самой волне лишь СОЗДАВАЛ неоднозначность — убран.
    except Exception as e:
        self.main.log(f"shortcuts error: {e}")
