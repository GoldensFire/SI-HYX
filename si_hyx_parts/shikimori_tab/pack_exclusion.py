# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Исключение паков: выбор .siq, сбор ответов и текстов вопросов, проверка тайтла.

Общий миксин ShikimoriHYX и «Поиска по сабам». Класс, который его наследует,
заводит в __init__ состояние (`init_pack_exclusion_state`), подпись `lbl_packs`
и реакцию на смену паков `_on_packs_changed`; для проверки франшиз ему нужны
`_collapse_franchise` и `_franchise_of` (id тайтла → franchise Shikimori).
Тайтл — любой объект с `id`, `title` и `name` (как `shikimori_api.Anime`).
"""
import shikimori_tab as _api


class PackExclusionMixin:
    """Исключение паков: выбор .siq, сбор ответов и текстов вопросов, проверка тайтла."""

    def init_pack_exclusion_state(self):
        """Пустое состояние исключения (зовётся из __init__ вкладки)."""
        self._excluded: set = set()    # нормализованные названия из паков
        self._excluded_bases: set = set()  # их «базовые» формы (без сезонов)
        self._excluded_franchises: set = set()  # их «ключи франшиз» (без подзаголовков)
        # Тексты вопросов из выбранных паков: название тайтла может не быть
        # ответом, а просто упоминаться в вопросе («Как называется аниме про…»).
        self._excluded_question_texts: set = set()
        self._excluded_question_haystack: str = ""
        self._question_term_cache: dict = {}
        self._name_excluded_memo: dict = {}  # anime_id -> название совпало с паком
        # Ключи франшиз самого Shikimori (manifest пака): по ним пак с «Атакой
        # титанов» прячет и «Атаку! Титанов средней школы», хотя названия разные.
        self._excluded_shiki_franchises: set = set()
        self._excluded_prefixes: set = set()  # индекс _franchise_prefix_index по ним
        self._excluded_packs: list = []  # имена выбранных паков SiQuesterHYX
        self._excluded_pack_files: list = []  # пути .siq, добавленных вручную
        # Ручные .siq со снятой галочкой: остаются в списке окна, но не исключают.
        self._disabled_pack_files: list = []
        self._pack_file_errors: set = set()  # выбранные файлы, которые не прочитать
        self._fkeys: dict = {}         # anime_id -> ключи франшизы по названиям

    def _on_packs_changed(self):
        """Паки выбраны заново — вкладка переприменяет исключение."""

    # ── Исключение паков ───────────────────────────────────────────────────────
    def _siq_datasets(self):
        """Список загруженных в SiQuesterHYX датасетов или [] если вкладки нет."""
        tsq = getattr(self.main, "tab_siquester", None) if self.main else None
        inner = getattr(tsq, "inner", None) if tsq else None
        return list(getattr(inner, "datasets", []) or []) if inner else []

    @staticmethod
    def _answer_variants(text: str) -> set:
        """Нормализованные варианты одного ответа.

        Один ответ нередко содержит несколько вариантов тайтла через « / » или
        « | » («Охотник x Охотник / Hunter x Hunter (1999)») — разбиваем, чтобы
        в исключения попал и русский, и ромадзи-вариант по отдельности. Делим
        только по разделителю С ПРОБЕЛАМИ, чтобы не рвать «Fate/stay».

        Ответ песенного вопроса генератора — «Мастера Меча Онлайн OP1 (2012) —
        『crossing field』»: целиком он ни с одним тайтлом не совпадёт, поэтому
        добавляем и голое название по правилу генератора (answer_title). Строки
        реплик вроде «Исполнитель — 『LiSA』» названием тайтла не считаем.
        """
        from animepack import answer_title
        out = set()
        for line in (text or "", answer_title(text)):
            for part in _api.re.split(r"\s+[/|]\s+", line):
                n = _api._norm_title(part)
                if n and n not in _api._ANSWER_LABELS:
                    out.add(n)
        return out

    def _pack_answers(self, ds) -> set:
        """Собирает нормализованные ответы из одного .siq-пака."""
        out = set()
        w = ds.get("widget")
        siq = getattr(w, "_siq", None) if w else None
        rounds = getattr(siq, "rounds", []) if siq else []
        for rd in rounds:
            for th in rd.get("themes", []):
                for q in th.get("questions", []):
                    answers = list(q.get("answers", []) or [])
                    for it in q.get("items", []) or []:
                        if (it.get("param") == "answer"
                                and it.get("type") == "text"
                                and not it.get("is_ref")):
                            answers.append(it.get("text", ""))
                    for ans in answers:
                        out |= self._answer_variants(ans)
        return out

    def _pack_question_texts(self, ds) -> set:
        """Тексты вопросов пака: название может быть только в вопросе, не в ответе.

        Устный текст (placement="replic") берём тоже — генератор пишет туда
        «Аниме: <название> (год)» рядом с видео вопроса."""
        out = set()
        w = ds.get("widget")
        siq = getattr(w, "_siq", None) if w else None
        rounds = getattr(siq, "rounds", []) if siq else []
        for rd in rounds:
            for th in rd.get("themes", []):
                for q in th.get("questions", []):
                    for it in q.get("items", []) or []:
                        if (it.get("param") == "question"
                                and it.get("type") == "text"
                                and not it.get("is_ref")):
                            n = _api._norm_title(it.get("text", ""))
                            if n:
                                out.add(n)
        return out

    @staticmethod
    def _pack_franchises(ds) -> set:
        """Ключи франшиз Shikimori из манифеста пака (у старых паков его нет).

        Названия у частей франшизы разные: «Атака титанов» и «Атака! Титаны
        средней школы», «Этот замечательный мир» и «Одаривая этот замечательный
        мир взрывами!». У Shikimori у них один franchise — по нему пак и должен
        прятать всю серию. Манифест пишется генератором рядом с content.xml.
        """
        path = str((ds or {}).get("siq_path") or "").strip()
        if not path:
            return set()
        try:
            from si_hyx_parts.animepack.pack_manifest import read as read_manifest
            rows = read_manifest(path)
        except Exception:  # noqa: BLE001 — чужой/битый пак просто без манифеста
            return set()
        return {str(key) for key in (rows.get("franchises") or ()) if key}

    def _collect_pack_terms(self, names, files):
        """(ответы, тексты вопросов, франшизы, нечитаемые файлы) из паков."""
        answers = set()
        questions = set()
        franchises = set()
        broken = []
        wanted = set(names)
        for idx, ds in enumerate(self._siq_datasets()):
            name = ds.get("pkg_name") or f"Пак {idx + 1}"
            if name not in wanted:
                continue
            answers |= self._pack_answers(ds)
            questions |= self._pack_question_texts(ds)
            franchises |= self._pack_franchises(ds)
        for raw_path in files:
            path = str(raw_path or "").strip()
            if not path:
                continue
            try:
                raw_answers, raw_questions = _api.read_pack_texts(path)
            except Exception:  # noqa: BLE001 — чужой/битый .siq просто пропускаем
                broken.append(path)
                continue
            for ans in raw_answers:
                answers |= self._answer_variants(ans)
            for text in raw_questions:
                n = _api._norm_title(text)
                if n:
                    questions.add(n)
            franchises |= self._pack_franchises({"siq_path": path})
        return answers, questions, franchises, broken

    def _refresh_packs_label(self):
        """Подпись под кнопкой: сколько паков и что из них прочитано."""
        names = list(self._excluded_packs)
        files = list(self._excluded_pack_files)
        if not names and not files:
            off = len(self._disabled_pack_files)
            self.lbl_packs.setText(
                f"Паки не выбраны (отключено файлов: {off})." if off
                else "Паки не выбраны.")
            self.lbl_packs.setToolTip("")
            return
        shown = names + [_api.os.path.basename(path) or path for path in files]
        text = (f"Выбрано паков: {len(names) + len(files)}. "
                f"Названий: {len(self._excluded)}, текстов вопросов: "
                f"{len(self._excluded_question_texts)}.\n" + ", ".join(shown))
        available = {ds.get("pkg_name") or f"Пак {idx + 1}"
                     for idx, ds in enumerate(self._siq_datasets())}
        missing = [name for name in names if name not in available]
        if missing:
            text += "\nНе открыты в SiQuesterHYX: " + ", ".join(missing)
        if self._disabled_pack_files:
            text += f"\nОтключено файлов: {len(self._disabled_pack_files)}"
        if self._pack_file_errors:
            text += "\nНе удалось прочитать: " + ", ".join(
                _api.os.path.basename(path) or path
                for path in self._excluded_pack_files
                if path in self._pack_file_errors)
        self.lbl_packs.setText(text)
        self.lbl_packs.setToolTip("\n".join(names + files))

    def _pack_picker_start(self) -> str:
        """Каталог для выбора .siq: прошлый выбор или папка загрузок."""
        for path in reversed(self._excluded_pack_files
                             + self._disabled_pack_files):
            folder = _api.os.path.dirname(path)
            if folder and _api.os.path.isdir(folder):
                return folder
        try:
            from utils import default_download_dir
            folder = default_download_dir()
            if folder:
                return folder
        except Exception:
            pass
        return _api.os.path.expanduser("~")

    @staticmethod
    def _add_pack_file_item(view, path: str, checked: bool = True):
        """Строка ручного .siq: галочка включает/выключает исключение без
        удаления файла из списка (как у паков SiQuesterHYX)."""
        item = _api.QListWidgetItem(_api.os.path.basename(path) or path)
        item.setData(_api.Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        item.setFlags(item.flags() | _api.Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(_api.Qt.CheckState.Checked if checked
                           else _api.Qt.CheckState.Unchecked)
        if not _api.os.path.isfile(path):
            item.setText(item.text() + "  (файл не найден)")
        view.addItem(item)

    @staticmethod
    def _pack_file_sort_key(path: str):
        """Естественный порядок по имени: «пак № 2» раньше «пак № 10»."""
        name = (_api.os.path.basename(path) or path).casefold()
        return [(0, int(part), "") if part.isdigit() else (1, 0, part)
                for part in _api.re.split(r"(\d+)", name)]

    def _choose_packs(self):
        datasets = self._siq_datasets()
        dlg = _api.QDialog(self)
        dlg.setWindowTitle("Паки для исключения")
        dlg.setMinimumWidth(560)  # четыре кнопки в одной строке
        lay = _api.QVBoxLayout(dlg)
        intro = _api.QLabel(
            "Тайтлы, которые встречаются в ответах или тексте вопросов "
            "выбранных паков, будут скрыты из выдачи поиска:")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        checks = []
        if datasets:
            lay.addWidget(_api.QLabel("Открыты в SiQuesterHYX:"))
            for idx, ds in enumerate(datasets):
                name = ds.get("pkg_name") or f"Пак {idx + 1}"
                cb = _api.QCheckBox(name)
                cb.setChecked(name in self._excluded_packs)
                lay.addWidget(cb)
                checks.append((cb, name))
        else:
            hint = _api.QLabel("В SiQuesterHYX паки не открыты — это не мешает "
                               "добавить файлы вручную.")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color:{_api.C['text3']}; font-size:11px;")
            lay.addWidget(hint)

        loaded = {name for _, name in checks}
        missing = [name for name in self._excluded_packs if name not in loaded]
        if missing:
            lay.addWidget(_api.QLabel("Сохранены, но не открыты в SiQuesterHYX:"))
            for name in missing:
                cb = _api.QCheckBox(name)
                cb.setChecked(True)
                cb.setToolTip(
                    "Пак сейчас не загружен, поэтому ничего не исключает. "
                    "Откройте его в SiQuesterHYX — и исключение заработает.")
                lay.addWidget(cb)
                checks.append((cb, name))

        line = _api.QFrame(); line.setFrameShape(_api.QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{_api.C['border']};")
        lay.addWidget(line)
        lay.addWidget(_api.QLabel(
            "Добавленные вручную .siq-файлы (галочка — исключать):"))
        file_list = _api.QListWidget()
        file_list.setSelectionMode(
            _api.QAbstractItemView.SelectionMode.ExtendedSelection)
        file_list.setMaximumHeight(150)
        off = set(self._disabled_pack_files)
        for path in sorted(self._excluded_pack_files + self._disabled_pack_files,
                           key=self._pack_file_sort_key):
            self._add_pack_file_item(file_list, path, path not in off)
        lay.addWidget(file_list)

        # Все четыре кнопки одной строкой: файлы слева, OK/Отмена справа.
        btn_row = _api.QHBoxLayout()
        btn_add = _api.QPushButton("Добавить файлы…")
        btn_add.setIcon(_api.get_icon('fa5s.folder-open'))
        btn_remove = _api.QPushButton("Убрать выбранные")
        btn_remove.setIcon(_api.get_icon('fa5s.trash'))
        btn_remove.setToolTip("Удалить выделенные строки из списка. "
                              "Чтобы временно не исключать пак, снимите галочку.")
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_remove)
        btn_row.addStretch(1)

        def add_files():
            paths, _ = _api.QFileDialog.getOpenFileNames(
                dlg, "Добавить паки для исключения", self._pack_picker_start(),
                "Пакеты SIGame (*.siq);;Все файлы (*)")
            have = {_api.os.path.normcase(_api.os.path.abspath(
                str(file_list.item(i).data(_api.Qt.ItemDataRole.UserRole) or "")))
                for i in range(file_list.count())}
            for path in paths:
                key = _api.os.path.normcase(_api.os.path.abspath(path))
                if key in have:
                    continue
                self._add_pack_file_item(file_list, path)
                have.add(key)

        def remove_files():
            for item in file_list.selectedItems():
                file_list.takeItem(file_list.row(item))

        btn_add.clicked.connect(add_files)
        btn_remove.clicked.connect(remove_files)

        bb = _api.QDialogButtonBox(_api.QDialogButtonBox.StandardButton.Ok
                              | _api.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        btn_row.addWidget(bb)
        lay.addLayout(btn_row)
        if dlg.exec() != _api.QDialog.DialogCode.Accepted:
            return

        chosen_names = [name for cb, name in checks if cb.isChecked()]
        chosen_files, disabled_files = [], []
        for i in range(file_list.count()):
            item = file_list.item(i)
            path = str(item.data(_api.Qt.ItemDataRole.UserRole) or "")
            if not path:
                continue
            if item.checkState() == _api.Qt.CheckState.Checked:
                chosen_files.append(path)
            else:
                disabled_files.append(path)
        self._disabled_pack_files = disabled_files
        answers, questions, franchises, broken = self._collect_pack_terms(
            chosen_names, chosen_files)
        self._excluded = answers
        self._excluded_question_texts = questions
        self._excluded_shiki_franchises = franchises
        self._excluded_packs = chosen_names
        self._excluded_pack_files = chosen_files
        self._pack_file_errors = set(broken)
        self._rebuild_excluded_bases()
        self._refresh_packs_label()
        self._on_packs_changed()


    def _restore_packs(self, names: list, files=None):
        """Восстанавливает исключаемые паки по именам и путям .siq."""
        wanted = set(names)
        found = [ds.get("pkg_name") or f"Пак {idx + 1}"
                 for idx, ds in enumerate(self._siq_datasets())
                 if (ds.get("pkg_name") or f"Пак {idx + 1}") in wanted]
        files = [str(path or "").strip() for path in (files or [])
                 if str(path or "").strip()]
        answers, questions, franchises, broken = self._collect_pack_terms(
            found, files)
        # Имена помним даже если паки ещё не открыты — попадут при следующем выборе.
        self._excluded_packs = list(names) or found
        self._excluded_pack_files = files
        self._excluded = answers
        self._excluded_question_texts = questions
        self._excluded_shiki_franchises = franchises
        self._pack_file_errors = set(broken)
        self._rebuild_excluded_bases()
        self._refresh_packs_label()


    def _term_in_question_text(self, term: str) -> bool:
        """Встречается ли название в тексте вопроса отдельным словом/фразой.

        Простое `in` дало бы ложные срабатывания на коротких названиях внутри
        других слов, поэтому проверяем границы слова (`\\w`). Результат кешируем:
        в выдаче тысячи тайтлов, а названий у них заметно меньше.

        Регулярку строим только для названий, которые есть в тексте простой
        подстрокой: re.search компилирует новый шаблон на каждое название, и
        на 20 тыс. тайтлах «По кэшу» это вешало вкладку на десятки секунд."""
        cache = self._question_term_cache
        if term in cache:
            return cache[term]
        found = False
        haystack = self._excluded_question_haystack
        if term and haystack and term in haystack:
            found = bool(_api.re.search(
                r"(?<!\w)" + _api.re.escape(term) + r"(?!\w)", haystack))
        cache[term] = found
        return found

    def _question_mentions(self, nt: str, nn: str) -> bool:
        """Название тайтла (или его корень) упомянуто в тексте вопроса."""
        if not self._excluded_question_haystack:
            return False
        terms = []
        for name in (nt, nn):
            if not name:
                continue
            for term in (name, _api._base_title(name),
                         _api._franchise_key(name)):
                if term and term not in terms:
                    terms.append(term)
        return any(self._term_in_question_text(term) for term in terms)

    def _name_excluded(self, a: '_api.Anime') -> bool:
        """Совпало ли НАЗВАНИЕ тайтла с ответом/текстом вопроса из пака.

        Ответ запоминается по id до смены паков (_rebuild_excluded_bases):
        за один проход его спрашивают и _learn_excluded_franchises, и
        _is_excluded, а потоковая выдача — ещё и на каждой странице."""
        if not self._excluded and not self._excluded_question_haystack:
            return False
        memo = self._name_excluded_memo
        hit = memo.get(a.id)
        if hit is None:
            hit = memo[a.id] = self._match_excluded_name(a)
        return hit

    def _match_excluded_name(self, a: '_api.Anime') -> bool:
        nt, nn = _api._norm_title(a.title), _api._norm_title(a.name)
        if nt in self._excluded or nn in self._excluded:
            return True
        # Сезонные варианты: пак с «Ванпанчмен» прячет и «Ванпанчмен 3» (и наоборот)
        # — сравниваем «базовые» формы без хвостового номера/«сезон N».
        if self._excluded_bases:
            if _api._base_title(nt) in self._excluded_bases:
                return True
            if nn and _api._base_title(nn) in self._excluded_bases:
                return True
        # Название могло быть только в ТЕКСТЕ вопроса (ответ — имя героя,
        # предмет или разгаданное слово), поэтому проверяем и его.
        return self._question_mentions(nt, nn)

    def _is_excluded(self, a: '_api.Anime') -> bool:
        if (not self._excluded and not self._excluded_question_haystack
                and not self._excluded_franchises):
            return False
        if self._name_excluded(a):
            return True
        # Франшиза целиком: пак с «Наруто» прячет «Наруто: Ураганные хроники».
        if self._collapse_franchise and self._excluded_franchises:
            keys = self._franchise_keys(a)
            for k in keys:
                if k in self._excluded_franchises:
                    return True
            # Длинные тайтлы одной франшизы, отличающиеся лишь последним словом
            # («…мечту девочки зайки» vs «…девочки-мечтательницы»).
            for k in keys:
                if _api._matches_franchise_prefix(k, self._excluded_prefixes):
                    return True
        return False

    def _learn_excluded_franchises(self, raw):
        """Закрывает франшизы исключённых паками тайтлов, даже если у пака нет
        манифеста.

        «Атака титанов» из пака и «Атака! Титаны средней школы» из выдачи —
        один franchise у Shikimori, хотя названия разные. В «По кэшу» карточки
        уже приносят franchise (cache_search); в сетевом поиске — после
        дозагрузки просмотров."""
        if ((not self._excluded and not self._excluded_question_haystack)
                or not self._franchise_of):
            return
        for a in raw:
            franchise = self._franchise_of.get(a.id)
            if not franchise or "#" + franchise in self._excluded_franchises:
                continue
            if self._name_excluded(a):
                self._excluded_shiki_franchises.add(franchise)
                self._excluded_franchises.add("#" + franchise)

    def _franchise_keys(self, a) -> set:
        """Ключи франшизы тайтла: по русскому названию, по ромадзи и, если тайтл
        есть в базе генератора, — ключ франшизы самого Shikimori. Последний
        ловит части, у которых название другое («Атака! Титаны средней школы»
        у «Атаки титанов»)."""
        keys = self._fkeys.get(a.id)
        if keys is None:
            keys = frozenset(k for k in (_api._franchise_key(a.title),
                                         _api._franchise_key(a.name)) if k)
            self._fkeys[a.id] = keys
        franchise = self._franchise_of.get(a.id)
        return keys | {"#" + franchise} if franchise else set(keys)

    def _rebuild_excluded_bases(self):
        """Пересобирает «базовые» формы и «ключи франшиз» исключённых названий."""
        self._excluded_bases = {b for b in (_api._base_title(x) for x in self._excluded) if b}
        name_keys = {f for f in (_api._franchise_key(x) for x in self._excluded) if f}
        # Ключ самого Shikimori живёт в отдельном пространстве имён («#konosuba»,
        # «#shingeki_no_kyojin») и с названием «атака титанов» не совпадает.
        # Он приходит из манифеста пака и ловит части с другим названием.
        self._excluded_franchises = name_keys | {
            "#" + f for f in self._excluded_shiki_franchises if f}
        self._excluded_prefixes = _api._franchise_prefix_index(name_keys)
        self._excluded_question_haystack = "\n".join(
            self._excluded_question_texts)
        self._question_term_cache = {}
        self._name_excluded_memo = {}
