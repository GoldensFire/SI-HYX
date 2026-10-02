# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackTab: _group_other. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


# ── группа «Прочее» ───────────────────────────────────────────────────
def _group_other(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Прочее")
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    # Подписи нарочно короткие: длинный текст в QCheckBox не переносится и
    # задаёт минимальную ширину всей панели. Подробности — в подсказках.
    # Галочек «Дубли аниме» и «Дубли франшиз» больше нет: и то, и другое
    # выключено навсегда (просьба пользователя). Один тайтл — один вопрос,
    # одна франшиза — один тайтл.
    self.chk_sort_index = _api.QCheckBox("По индексу популярности")
    self.chk_sort_index.setToolTip(
        "Порядок вопросов и их цены берутся из «индекса популярности» — той "
        "же величины, по которой сортирует вкладка ShikimoriHYX (списки "
        "пользователей, взвешенные на свежесть выхода и слегка на оценку). "
        "Пак идёт от самых узнаваемых тайтлов к самым безвестным: самый "
        "узнаваемый вопрос стоит 2, самый редкий — 20.\n"
        "Выключено — цены считаются по сложности угадывания из AMQ.")
    # Отрезок песни, коллаж, подсказка о типе, сжатие дорожки, Chiptune и
    # каверы живут не здесь: всё, что про музыку, собрано под галочкой «Песни»
    # в составе пака (music_panel — просьба пользователя).
    # Сколько висит постер в ответе. Раньше это были зашитые три секунды.
    self.sp_answer_img = _api.QSpinBox()
    self.sp_answer_img.setRange(0, _api.ANSWER_IMAGE_MAX)
    self.sp_answer_img.setValue(3); self.sp_answer_img.setSuffix(" с")
    self.sp_answer_img.setMinimumWidth(74)
    self.sp_answer_img.setSpecialValueText("без ограничения")
    self.sp_answer_img.setToolTip(
        "Сколько секунд показывается постер тайтла в ОТВЕТЕ на вопрос.\n"
        f"Больше {_api.ANSWER_IMAGE_MAX} с не ставится: всё нужное с постера "
        "считывается за пару секунд, а игра тем временем стоит.\n"
        "«без ограничения» (ноль) — картинка остаётся на экране, пока "
        "ведущий не перейдёт дальше.")
    # ── Повторно используемые медиа и запасной источник обложек ────────
    self.chk_poster_cache = _api.QCheckBox("Хранить медиа в кэше на диске")
    self.chk_poster_cache.setChecked(True)
    self.chk_poster_cache.setToolTip(
        "Постеры, исходное аудио, кадры и готовые AVIF сохраняются рядом с "
        "настройками и при повторной генерации не скачиваются или не "
        "кодируются заново. Кэш постеров общий с вкладкой «Апгрейд пака».\n"
        "Случайные готовые вопросы и уникальные арты не сохраняются, чтобы "
        "паки не начинали повторяться.\n"
        f"Общий потолок — {_api.POSTER_CACHE_MB + _api.MEDIA_CACHE_MB} МБ; "
        "старые неиспользуемые файлы удаляются первыми.")
    self.chk_poster_cache.toggled.connect(self._on_poster_cache_toggled)
    self.btn_poster_clear = _api.QPushButton("Очистить")
    self.btn_poster_clear.setToolTip(
        "Удалить сохранённые постеры, аудио, кадры и готовые AVIF.")
    self.btn_poster_clear.clicked.connect(self._clear_poster_cache)
    self.btn_cache_view = _api.QPushButton("Файлы кэша…")
    self.btn_cache_view.setToolTip(
        "Посмотреть сохранённые файлы, открыть их или удалить выборочно.")
    self.btn_cache_view.clicked.connect(self._open_cache_dialog)
    self.lbl_poster_cache = _api.QLabel("")
    self.btn_tmdb_key = self._api_key_button("tmdb", "Ключ TMDB")
    self.sp_parallel = _api.QSpinBox(); self.sp_parallel.setRange(1, 16)
    self.sp_parallel.setValue(8); self.sp_parallel.setMinimumWidth(44)
    self.sp_parallel.setToolTip("Сколько вопросов качается одновременно.")
    self.chk_compress_images = _api.QCheckBox("Сжимать картинки")
    self.chk_compress_images.setChecked(True)
    self.chk_compress_images.setToolTip(
        "Включено — постеры и кадры пережимаются в AVIF тем же кодером, что "
        "и во вкладке «Обработка», с низким приоритетом процесса (работать "
        "за компьютером не мешает).\n"
        "Выключено — картинка кладётся в пак как есть, оригиналом с "
        "Shikimori: быстро, но пак тяжелее в разы.")
    self.chk_compress_images.toggled.connect(self._on_compress_images_toggled)
    self.sp_img_kb = _api.QSpinBox(); self.sp_img_kb.setRange(20, 2000)
    self.sp_img_kb.setValue(150); self.sp_img_kb.setSuffix(" КБ")
    self.sp_img_kb.setSingleStep(10); self.sp_img_kb.setMinimumWidth(74)
    self.sp_img_kb.setToolTip("До скольки ужимать каждую картинку.")
    self.sp_img_speed = _api.QSpinBox(); self.sp_img_speed.setRange(0, 8)
    self.sp_img_speed.setValue(8); self.sp_img_speed.setMinimumWidth(44)
    self.sp_img_speed.setToolTip(
        "Скорость кодирования AVIF (-cpu-used): 8 — самая быстрая, 0 — "
        "самая медленная и качественная. На 8 картинка считается меньше "
        "секунды, на 5 — секунд пять.")

    # «Сжимать аудио» стоит РЯДОМ со «Сжимать картинки» (просьба
    # пользователя): обе галочки про вес пака, и искать их логично вместе, а
    # не в настройках песенных вопросов. Сама подсказка осталась в
    # music_panel — она про звук отрезка.
    from .music_panel import COMPRESS_TIP
    self.chk_compress_audio = _api.QCheckBox("Сжимать аудио")
    self.chk_compress_audio.setChecked(True)
    self.chk_compress_audio.setToolTip(COMPRESS_TIP)

    r = 0
    g.addWidget(self.chk_compress_images, r, 0, 1, 4)
    r += 1
    # Настройки сжатия картинок видны, только когда оно включено.
    self.box_img_opts = _api.SettingsBox()
    ig = _api.QGridLayout(self.box_img_opts)
    ig.setContentsMargins(16, 0, 0, 0)
    ig.setHorizontalSpacing(8); ig.setVerticalSpacing(6)
    ig.addWidget(self._lab("Сжимать до"), 0, 0)
    ig.addWidget(self.sp_img_kb, 0, 1)
    ig.addWidget(self._lab("Скорость"), 1, 0)
    ig.addWidget(self.sp_img_speed, 1, 1)
    ig.setColumnStretch(1, 1)
    g.addWidget(self.box_img_opts, r, 0, 1, 4)
    r += 1
    g.addWidget(self.chk_compress_audio, r, 0, 1, 4)
    r += 1
    self.chk_shuffle = _api.QCheckBox("Вопросы в разнобой")
    self.chk_shuffle.setToolTip(
        "Включено — вопросы в теме идут случайно, а не от дешёвых к "
        "дорогим: цена по теме скачет, как в живых паках.")
    g.addWidget(self.chk_shuffle, r, 0, 1, 4)
    r += 1
    g.addWidget(self.chk_sort_index, r, 0, 1, 4)
    r += 1
    g.addWidget(self._lab("Картинка в ответе"), r, 0, 1, 2)
    g.addWidget(self.sp_answer_img, r, 2, 1, 2)
    r += 1
    g.addWidget(self.chk_poster_cache, r, 0, 1, 2)
    g.addWidget(self.btn_cache_view, r, 2)
    g.addWidget(self.btn_poster_clear, r, 3)
    r += 1
    # Подпись «сколько обложек лежит» прячется вместе с галочкой, а ключ
    # TMDB — нет: запасной источник работает и без кладовой.
    g.addWidget(self.lbl_poster_cache, r, 0, 1, 4)
    # Подпись «сколько обложек лежит» нужна и без сохранённых настроек:
    # свежая вкладка иначе показывала бы пустую строку.
    self._refresh_poster_cache()
    r += 1
    g.addWidget(self._lab("Ключ TMDB"), r, 0, 1, 2)
    g.addWidget(self.btn_tmdb_key, r, 2, 1, 2)
    r += 1
    g.addWidget(self._lab("Параллельных загрузок"), r, 0, 1, 3)
    g.addWidget(self.sp_parallel, r, 3)
    r += 1
    # Готовые паки, чьи франшизы повторять не надо.
    excl_row = _api.QHBoxLayout(); excl_row.setSpacing(6)
    self.btn_excl_siq = _api.QPushButton("Не повторять франшизы из паков…")
    self.btn_excl_siq.setIcon(_api.get_icon('fa5s.file-import'))
    self.btn_excl_siq.setToolTip(
        "Выберите готовые .siq — программа прочитает их правильные ответы и "
        "не станет спрашивать те же франшизы снова. «Наруто» из старого "
        "пака закроет и «Наруто: Ураганные хроники» в новом.\n"
        "Читается только content.xml, медиа из архива не достаётся — это "
        "доли секунды на файл.")
    self.btn_excl_siq.clicked.connect(self._choose_exclude_siq)
    self.btn_excl_clear = _api.QPushButton("Очистить")
    self.btn_excl_clear.setToolTip("Убрать все паки из списка исключений.")
    self.btn_excl_clear.clicked.connect(self._clear_exclude_siq)
    self.btn_excl_list = _api.QPushButton("Изменить…")
    self.btn_excl_list.setToolTip("Добавить или убрать паки в списке.")
    self.btn_excl_list.clicked.connect(
        lambda: self._show_exclude_siq(False))
    excl_row.addWidget(self.btn_excl_siq, 1)
    excl_row.addWidget(self.btn_excl_list)
    excl_row.addWidget(self.btn_excl_clear)
    g.addLayout(excl_row, r, 0, 1, 4)
    r += 1
    self.lbl_excl_siq = self._hint("")
    g.addWidget(self.lbl_excl_siq, r, 0, 1, 4)
    r += 1
    exact_row = _api.QHBoxLayout(); exact_row.setSpacing(6)
    self.btn_exact_siq = _api.QPushButton("Не повторять из паков (те же вопросы)…")
    self.btn_exact_siq.setToolTip(
        "Пропускать только уже заданные вопросы: тот же OP/ED, тот же "
        "видеофрагмент сакуги, тот же сюжетный факт или то же медиа. "
        "Другие вопросы по этому аниме остаются доступны.")
    self.btn_exact_siq.clicked.connect(self._choose_exact_siq)
    self.btn_exact_clear = _api.QPushButton("Очистить")
    self.btn_exact_clear.clicked.connect(self._clear_exact_siq)
    self.btn_exact_list = _api.QPushButton("Изменить…")
    self.btn_exact_list.setToolTip("Добавить или убрать паки в списке.")
    self.btn_exact_list.clicked.connect(
        lambda: self._show_exclude_siq(True))
    exact_row.addWidget(self.btn_exact_siq, 1)
    exact_row.addWidget(self.btn_exact_list)
    exact_row.addWidget(self.btn_exact_clear)
    g.addLayout(exact_row, r, 0, 1, 4)
    r += 1
    self.lbl_exact_siq = self._hint("")
    g.addWidget(self.lbl_exact_siq, r, 0, 1, 4)
    r += 1
    self.chk_auto_add_exclusions = _api.QCheckBox(
        "Добавлять готовые паки в «не повторять»")
    self.chk_auto_add_exclusions.setChecked(True)
    self.chk_auto_add_exclusions.setToolTip(
        "После сохранения пака добавить его в оба списка выше: запрет "
        "франшиз и запрет тех же вопросов. Выключено — списки меняются "
        "только вручную. Для запущенного пака действует выбор на момент запуска.")
    g.addWidget(self.chk_auto_add_exclusions, r, 0, 1, 4)
    r += 1
    self.chk_ignore_test_packs = _api.QCheckBox("Не считать тестовые паки")
    self.chk_ignore_test_packs.setToolTip(
        "Паки меньше 96 вопросов получают отдельное имя «Тестовый № …», "
        "не занимают обычный номер и не исключают франшизы и вопросы "
        "из следующих паков.")
    g.addWidget(self.chk_ignore_test_packs, r, 0, 1, 4)
    r += 1
    self.btn_out_dir = _api.QPushButton("Папка для пака…")
    self.btn_out_dir.setIcon(_api.get_icon('fa5s.folder'))
    self.btn_out_dir.clicked.connect(self._choose_out_dir)
    g.addWidget(self.btn_out_dir, r, 0, 1, 4)
    r += 1
    self.lbl_out_dir = self._hint("")
    g.addWidget(self.lbl_out_dir, r, 0, 1, 4)
    for col in (1, 3):
        g.setColumnStretch(col, 1)
    self._refresh_out_dir_label()
    self._refresh_exclude_label()
    self._refresh_exact_label()
    return grp

# ── исключение франшиз по чужим пакам ─────────────────────────────────
def _choose_exclude_siq(self):
    paths, _ = _api.QFileDialog.getOpenFileNames(
        self, "Паки, франшизы из которых не повторять",
        self._pack_picker_start(),
        "Пакеты SIGame (*.siq);;Все файлы (*)")
    if not paths:
        return
    have = {_api.os.path.normcase(p) for p in self._exclude_siq}
    for path in paths:
        if _api.os.path.normcase(path) not in have:
            self._exclude_siq.append(path)
            have.add(_api.os.path.normcase(path))
    self._refresh_exclude_label()

def _clear_exclude_siq(self):
    self._exclude_siq = []
    self._refresh_exclude_label()


def _show_exclude_siq(self, exact: bool):
    """Открыть редактируемый список одного из двух запретов повторов."""
    from .pack_list_dialog import show_included_packs
    paths = (self._exclude_exact_siq if exact else self._exclude_siq)
    title = ("Паки с уже заданными вопросами" if exact else
             "Паки с исключёнными франшизами")
    attr = "_exact_list_dialog" if exact else "_franchise_list_dialog"
    old = getattr(self, attr, None)
    if old is not None:
        old.close()

    def changed(new_paths):
        if exact:
            self._exclude_exact_siq = list(new_paths)
            self._refresh_exact_label()
        else:
            self._exclude_siq = list(new_paths)
            self._refresh_exclude_label()

    setattr(self, attr, show_included_packs(
        self, title, list(paths), self._pack_picker_start(), changed,
        search_questions=exact))

def _refresh_exclude_label(self):
    n = len(self._exclude_siq)
    if not n:
        self.lbl_excl_siq.setText("Исключений нет: пак собирается без "
                                  "оглядки на другие.")
        self.btn_excl_clear.setEnabled(False)
        self.btn_excl_list.setEnabled(True)
        return
    names = ", ".join(_api.os.path.basename(p) for p in self._exclude_siq[:3])
    if n > 3:
        names += f" и ещё {n - 3}"
    self.lbl_excl_siq.setText(f"Не повторяю франшизы из {n} пак(ов): {names}")
    self.lbl_excl_siq.setToolTip("\n".join(self._exclude_siq))
    self.btn_excl_clear.setEnabled(True)
    self.btn_excl_list.setEnabled(True)


def _choose_exact_siq(self):
    paths, _ = _api.QFileDialog.getOpenFileNames(
        self, "Паки, вопросы из которых не повторять",
        self._pack_picker_start(),
        "Пакеты SIGame (*.siq);;Все файлы (*)")
    have = {_api.os.path.normcase(p) for p in self._exclude_exact_siq}
    for path in paths:
        if _api.os.path.normcase(path) not in have:
            self._exclude_exact_siq.append(path)
            have.add(_api.os.path.normcase(path))
    self._refresh_exact_label()


def _clear_exact_siq(self):
    self._exclude_exact_siq = []
    self._refresh_exact_label()


def _refresh_exact_label(self):
    count = len(self._exclude_exact_siq)
    self.lbl_exact_siq.setText(
        f"Не повторяю сами вопросы из {count} пак(ов)." if count else
        "Точные повторы из паков пока не исключаются.")
    self.lbl_exact_siq.setToolTip("")
    self.btn_exact_clear.setEnabled(bool(count))
    self.btn_exact_list.setEnabled(True)


def _pack_picker_start(self) -> str:
    """Каталог, куда реально попадёт пак при текущих настройках."""
    if self._out_dir:
        return self._out_dir
    try:
        from utils import default_download_dir
        return default_download_dir()
    except Exception:
        return _api.os.path.expanduser("~")
