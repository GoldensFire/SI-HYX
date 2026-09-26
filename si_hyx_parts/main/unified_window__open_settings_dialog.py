# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""UnifiedWindow: _open_settings_dialog. Public namespace: main."""
import main as _api


def _open_settings_dialog(self, section=None):
    """section — имя раздела, к которому сразу перейти (например, «Ключи API»).

    Кнопки «задан / не задан» ключей обещают открыть именно этот раздел.
    clicked(bool) передаёт сюда False — это «без раздела».
    """
    dlg = _api.QDialog(self)
    dlg.setWindowTitle("Настройки — " + _api.APP_TITLE)
    dlg.setMinimumSize(680, 520)
    outer = _api.QVBoxLayout(dlg); outer.setSpacing(10); outer.setContentsMargins(12, 12, 12, 12)

    # ── Поиск по настройкам ──────────────────────────────────────────────
    search = _api.QLineEdit()
    search.setPlaceholderText("Поиск настроек…")
    search.addAction(_api.get_icon('fa5s.search'),
                     _api.QLineEdit.ActionPosition.LeadingPosition)
    search.setClearButtonEnabled(True)
    outer.addWidget(search)

    body = _api.QHBoxLayout(); body.setSpacing(10)
    outer.addLayout(body, 1)

    # ── Левая навигация (категории) ──────────────────────────────────────
    nav = _api.QListWidget()
    nav.setFixedWidth(160)
    nav.setStyleSheet(
        "QListWidget{background:#181825;border:1px solid #45475a;border-radius:6px;"
        "padding:4px;outline:none;}"
        "QListWidget::item{padding:8px 10px;border-radius:5px;color:#cdd6f4;}"
        "QListWidget::item:selected{background:#89b4fa;color:#1e1e2e;font-weight:bold;}"
        "QListWidget::item:hover:!selected{background:#313244;}")
    body.addWidget(nav)

    # ── Правая прокручиваемая область со всеми секциями ───────────────────
    scroll = _api.QScrollArea(); scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = _api.QWidget(); content_l = _api.QVBoxLayout(content)
    content_l.setContentsMargins(4, 4, 8, 4); content_l.setSpacing(14)
    scroll.setWidget(content)
    body.addWidget(scroll, 1)

    sections = []  # [{'name','widget','header','layout','rows':[(w,keywords)]}]

    def make_section(name):
        sec = _api.QWidget()
        secl = _api.QVBoxLayout(sec); secl.setContentsMargins(0, 0, 0, 0); secl.setSpacing(10)
        hdr = _api.QLabel(name)
        hdr.setStyleSheet("font-size:16px; font-weight:bold; color:#89b4fa; padding-top:2px;")
        secl.addWidget(hdr)
        rec = {'name': name, 'widget': sec, 'header': hdr, 'layout': secl, 'rows': []}
        sections.append(rec)
        content_l.addWidget(sec)
        nav.addItem(name)
        return rec

    def add_row(rec, widget, keywords=""):
        rec['layout'].addWidget(widget)
        rec['rows'].append((widget, (rec['name'] + " " + keywords).lower()))

    def hint(text):
        lbl = _api.QLabel(text)
        lbl.setStyleSheet("color:#a6adc8; font-size:11px;")
        lbl.setWordWrap(True)
        return lbl

    # ══ Секция «Основное» ════════════════════════════════════════════════
    sec_main = make_section("Основное")

    grp_ui = _api.QGroupBox("Интерфейс")
    vui = _api.QVBoxLayout(grp_ui)
    chk_wheel = _api.QCheckBox("Колёсико мыши меняет значения в полях")
    chk_wheel.setChecked(bool(self._wheel_changes_values))
    chk_wheel.toggled.connect(self._set_wheel_changes_values)
    vui.addWidget(chk_wheel)
    vui.addWidget(hint("Выкл — колёсико над полями прокручивает панель, а не меняет числа."))
    add_row(sec_main, grp_ui, "колесо мышь интерфейс значения прокрутка битрейт ползунки")

    grp_ai = _api.QGroupBox("Фото — нейросети")
    vai = _api.QVBoxLayout(grp_ai)
    chk_keep = _api.QCheckBox("Не выгружать модели нейронок из ОЗУ")
    chk_keep.setChecked(bool(getattr(self, "_keep_models_in_ram", False)))
    chk_keep.toggled.connect(self._set_keep_models_in_ram)
    vai.addWidget(chk_keep)
    vai.addWidget(hint("Выкл (по умолч.): модели удаления объектов/фона выгружаются из памяти "
                       "через минуту простоя или при уходе со вкладки «Фото» (освобождается ~1–2 ГБ; "
                       "следующий запуск ждёт перезагрузку модели). Вкл — держать в ОЗУ всегда (быстрее)."))
    add_row(sec_main, grp_ai, "нейросеть модель озу память выгрузка lama rmbg удаление объект фон фото")

    grp_enc = _api.QGroupBox("Обработка — продвинутые настройки")
    venc = _api.QVBoxLayout(grp_enc)
    chk_adv_enc = _api.QCheckBox("Показывать Тюнинг / Метрику (XPSNR) / CQ-level")
    chk_adv_enc.setChecked(bool(getattr(self, "_show_advanced_encode", False)))
    chk_adv_enc.toggled.connect(self._set_advanced_encode_visible)
    venc.addWidget(chk_adv_enc)
    venc.addWidget(hint("Выкл по умолчанию — три поля скрыты во вкладке «Обработка», "
                        "чтобы не путать в базовом сценарии (используются ручной CRF и CQ по умолчанию). "
                        "Включите, если нужно тонко настроить тюнинг SVT-AV1, авто-подбор CRF по XPSNR "
                        "или ручной уровень качества AVIF."))
    add_row(sec_main, grp_enc, "обработка тюнинг метрика xpsnr cq level cq-level crf продвинутые расширенные")

    # ══ Секция «Монтаж» ══════════════════════════════════════════════════
    sec_edit = make_section("Монтаж")

    grp_keys = _api.QGroupBox("Сочетания обрезки")
    vk = _api.QVBoxLayout(grp_keys)
    te = getattr(self, "tab_edit", None)
    if te is not None and getattr(te, "_ready", False):
        start_seq, end_seq = te.get_trim_shortcuts()

        def _mk_key_row(label_text, init_seq, apply_idx):
            row = _api.QHBoxLayout()
            lbl = _api.QLabel(label_text)
            lbl.setStyleSheet("color:#cdd6f4; font-size:12px;")
            lbl.setFixedWidth(230)
            kse = _api.LatinKeySequenceEdit()
            kse.setKeySequence(_api.QKeySequence(init_seq))
            row.addWidget(lbl); row.addWidget(kse, 1)
            w = _api.QWidget(); w.setLayout(row)
            return w, kse

        row_start, kse_start = _mk_key_row("Обрезать старт до плейхеда", start_seq, 0)
        row_end,   kse_end   = _mk_key_row("Обрезать конец до плейхеда", end_seq, 1)
        vk.addWidget(row_start)
        vk.addWidget(row_end)

        def _apply_keys():
            te.set_trim_shortcuts(
                kse_start.keySequence().toString(),
                kse_end.keySequence().toString())

        kse_start.editingFinished.connect(_apply_keys)
        kse_end.editingFinished.connect(_apply_keys)
        kse_start.keySequenceChanged.connect(lambda *_: _apply_keys())
        kse_end.keySequenceChanged.connect(lambda *_: _apply_keys())

        btn_reset = _api.QPushButton("Сбросить по умолчанию (Shift+C / Shift+V)")
        def _reset_keys():
            kse_start.setKeySequence(_api.QKeySequence("Shift+C"))
            kse_end.setKeySequence(_api.QKeySequence("Shift+V"))
            te.set_trim_shortcuts("Shift+C", "Shift+V")
        btn_reset.clicked.connect(_reset_keys)
        vk.addWidget(btn_reset)
        vk.addWidget(hint("Кликните в поле и нажмите нужную комбинацию. «Старт» "
                          "ставит точку IN, «Конец» — точку OUT на текущую позицию "
                          "воспроизведения."))
    else:
        vk.addWidget(hint("Вкладка «Монтаж» недоступна (нет модуля мультимедиа), "
                          "настройка сочетаний невозможна."))
    add_row(sec_edit, grp_keys, "монтаж обрезка сочетание клавиши shift c v плейхед старт конец in out горячие")

    # Блок «Покадровая перемотка» убран: скраб-звук теперь всегда включён.

    grp_render = _api.QGroupBox("Видео и оверлеи")
    vr = _api.QVBoxLayout(grp_render)

    # Настройка «Субтитры рендерить прямо в кадр» убрана: зафиксирована
    # значением по умолчанию (рендер в кадр, как в VLC).

    chk_hw = _api.QCheckBox("Аппаратное ускорение видео (H.264 / HEVC)")
    chk_hw.setChecked(bool(getattr(self, "_video_hw_decode", True)))
    chk_hw.toggled.connect(self._set_video_hw_decode)
    vr.addWidget(chk_hw)
    vr.addWidget(hint("Вкл (по умолч.): H.264/HEVC декодируются на видеокарте (D3D11VA/DXVA2) "
                      "— тяжёлые файлы в «Монтаже» играют плавно. Выключите, если прямой AV1 "
                      "(SiQuesterHYX) даёт чёрный экран. Нужен перезапуск."))

    # Настройка «Программный рендер видео» убрана: программный рендер
    # отключён всегда (видео идёт по аппаратному D3D/GL-свопчейну).
    add_row(sec_edit, grp_render, "оверлей fps d3d11 рендер видео аппаратное ускорение hevc h264 dxva декодирование")

    # ══ Секция «Ключи API» ═══════════════════════════════════════════════
    # Единственное место ввода ключей на всю программу: раньше поле висело
    # в каждой вкладке, которой ключ нужен (Генерация аниме-пака), и один и
    # тот же ключ приходилось вбивать по нескольку раз.
    sec_api = make_section("Ключи API")

    def _key_row(box_layout, label_html, placeholder, name, note):
        lbl = _api.QLabel(label_html)
        lbl.setOpenExternalLinks(True)
        lbl.setTextInteractionFlags(_api.Qt.TextInteractionFlag.TextBrowserInteraction)
        lbl.setWordWrap(True)
        box_layout.addWidget(lbl)
        ed = _api.QLineEdit(self.get_api_key(name))
        ed.setPlaceholderText(placeholder)
        ed.setEchoMode(_api.QLineEdit.EchoMode.Password)
        ed.setClearButtonEnabled(True)
        ed.textChanged.connect(lambda t, n=name: self.set_api_key(n, t))
        box_layout.addWidget(ed)
        box_layout.addWidget(hint(note))
        return ed

    grp_gemini = _api.QGroupBox("Gemini (Google AI Studio)")
    vg = _api.QVBoxLayout(grp_gemini)
    _key_row(vg,
             'Бесплатный ключ: <a href="https://aistudio.google.com/apikey" '
             'style="color:#89b4fa;">aistudio.google.com/apikey</a>',
             "Ключ Gemini API", "gemini",
             "Нужен вкладке «Генерация аниме-пака» (сюжет, перевод диалогов). Без "
             "ключа вкладка работает, просто без этой возможности. Тексты "
             "уходят в Google.")
    add_row(sec_api, grp_gemini,
            "gemini гемини google ключ api нейросеть повторы сюжет аниме aistudio")

    grp_subdl = _api.QGroupBox("SubDL — русские субтитры")
    vs = _api.QVBoxLayout(grp_subdl)
    _key_row(vs,
             'Ключ учётной записи: <a href="https://subdl.com/panel/api" '
             'style="color:#89b4fa;">subdl.com/panel/api</a>',
             "Ключ SubDL API", "subdl",
             "Первый источник вопросов «Диалоги из аниме»: субтитры сразу на "
             "русском, Gemini не нужен. Когда суточная квота ключа кончится, "
             "диалоги берутся из Jimaku. Ключ уходит только на api.subdl.com "
             "и в пак не попадает.")
    add_row(sec_api, grp_subdl,
            "subdl сабдл субтитры русские диалоги аниме ключ api серии")

    grp_jimaku = _api.QGroupBox("Jimaku — субтитры аниме")
    vj = _api.QVBoxLayout(grp_jimaku)
    _key_row(vj,
             'Ключ учётной записи: <a href="https://jimaku.cc/account" '
             'style="color:#89b4fa;">jimaku.cc/account</a>',
             "Ключ Jimaku API", "jimaku",
             "Нужен только вопросам «Диалоги из аниме». Субтитры ищутся по "
             "точному AniList ID; Gemini переводит выбранные реплики на "
             "русский. Ключ уходит только в заголовке запроса и в пак не "
             "попадает.")
    add_row(sec_api, grp_jimaku,
            "jimaku джимаку субтитры диалоги аниме ключ api серии")

    grp_tmdb = _api.QGroupBox("TMDB (themoviedb.org)")
    vt = _api.QVBoxLayout(grp_tmdb)
    _key_row(vt,
             'Бесплатный ключ: <a href="https://www.themoviedb.org/settings/api" '
             'style="color:#89b4fa;">themoviedb.org → настройки профиля → API</a>',
             "Ключ TMDB (необязательно)", "tmdb",
             "ЗАПАСНОЙ источник обложек для вкладок «Генерация аниме-пака» и "
             "«Апгрейд пака»: идёт в дело там, где у карточки Shikimori "
             "постера нет вовсе или ссылка не открылась. В кино-паке нужнее "
             "всего: у Wikidata афиша есть далеко не у каждого фильма. "
             "Годятся оба вида ключа — старый «API Key» и токен «API Read "
             "Access». Пусто — обложки берутся только из основной базы.")
    add_row(sec_api, grp_tmdb,
            "tmdb themoviedb обложка постер ключ api аниме запасной источник")

    grp_pixiv = _api.QGroupBox("Pixiv — арты аниме")
    vp = _api.QVBoxLayout(grp_pixiv)
    _key_row(vp,
             '<a href="https://www.pixiv.net/" style="color:#89b4fa;">Pixiv</a>',
             "Refresh token Pixiv", "pixiv",
             "Нужен только для вопросов «Арты Pixiv» в генераторе аниме-пака. "
             "Используется OAuth refresh token вашей учётной записи; пароль "
             "приложение не запрашивает и не хранит. R-18 и ИИ-арты можно "
             "исключить отдельными настройками во вкладке генератора; "
             "шок-контент блокируется всегда.")
    add_row(sec_api, grp_pixiv,
            "pixiv пиксив арт аниме oauth refresh token ключ api картинки")

    grp_cloudflare = _api.QGroupBox("Cloudflare — ИИ-арты")
    vc = _api.QVBoxLayout(grp_cloudflare)
    account = _key_row(vc, "Account ID", "32 символа из кабинета Cloudflare",
                       "cloudflare_account_id",
                       "Workers AI → Use REST API → Account ID.")
    account.setEchoMode(_api.QLineEdit.EchoMode.Normal)
    _key_row(vc,
             '<a href="https://developers.cloudflare.com/workers-ai/get-started/rest-api/" '
             'style="color:#89b4fa;">Как получить токен Cloudflare</a>',
             "Токен Workers AI", "cloudflare",
             "Создайте Workers AI API Token с правами Read и Edit. "
             "Для отображения остатка квоты добавьте Account → Account Analytics → Read. "
             "Модель выбирается во вкладке генерации аниме-пака. "
             "На бесплатном плане после исчерпания суточной квоты генерация остановится.")
    add_row(sec_api, grp_cloudflare,
            "cloudflare flux ии арты картинки генерация токен ключ account id")

    # ══ Секция «Экспериментально» (предпоследняя) ════════════════════════
    sec_exp = make_section("Экспериментально")

    grp_sv = _api.QGroupBox("Браузерное расширение")
    vsv = _api.QVBoxLayout(grp_sv)
    chk = _api.QCheckBox(f"Включить локальный сервер (localhost:{_api.HTTP_PORT})")
    chk.setChecked(bool(self._server_enabled))
    chk.toggled.connect(self._set_server_enabled)
    vsv.addWidget(chk)
    vsv.addWidget(hint("Выкл по умолчанию. Включите, чтобы расширение в браузере "
                       "слало ссылки в программу."))
    add_row(sec_exp, grp_sv, "браузер расширение сервер localhost порт ссылки экспериментально")

    grp_siq = _api.QGroupBox("Дополнительные вкладки")
    vexp = _api.QVBoxLayout(grp_siq)
    chk_prompt = _api.QCheckBox("Включить вкладку «Промпт»")
    chk_prompt.setChecked(bool(getattr(self, "_prompt_tab_enabled", False)))
    chk_prompt.toggled.connect(self._set_prompt_tab_enabled)
    vexp.addWidget(chk_prompt)
    vexp.addWidget(hint("Менеджер промптов: хранение и быстрый выбор заготовок."))
    chk_siq = _api.QCheckBox("Включить вкладку «SiQuesterHYX» (просмотр .siq + статистика)")
    chk_siq.setChecked(bool(getattr(self, "_siquester_tab_enabled", False)))
    chk_siq.toggled.connect(self._set_siquester_tab_enabled)
    vexp.addWidget(chk_siq)
    vexp.addWidget(hint(_api.icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                        + " Вам это не надо. Просмотрщик пакетов SIGame (.siq) и "
                        "статистика."))
    chk_shiki = _api.QCheckBox("Включить вкладку «ShikimoriHYX» (поиск аниме по Shikimori API)")
    chk_shiki.setChecked(bool(getattr(self, "_shikimori_tab_enabled", False)))
    chk_shiki.toggled.connect(self._set_shikimori_tab_enabled)
    vexp.addWidget(chk_shiki)
    vexp.addWidget(hint(_api.icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                        + " Экспериментально. Поиск аниме через Shikimori API с фильтрами, сортировка по индексу популярности, нужен, если вы делаете аниме пак, пишите в лс, если будете пользоваться - объясню; "
            ))
    chk_lb = _api.QCheckBox("Включить вкладку «ЛидербордHYX» (просмотр выгрузки рекордов)")
    chk_lb.setChecked(bool(getattr(self, "_leaderboard_tab_enabled", False)))
    chk_lb.toggled.connect(self._set_leaderboard_tab_enabled)
    vexp.addWidget(chk_lb)
    vexp.addWidget(hint(_api.icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                        + " Загрузите JSON-выгрузку лидерборда из Firebase — увидите "
                        "никнеймы с их рекордами и сможете убрать ник из списка."))
    chk_coop = _api.QCheckBox("Включить вкладку «Collab» (совместная работа над .siq)")
    chk_coop.setChecked(bool(getattr(self, "_coop_tab_enabled", False)))
    chk_coop.toggled.connect(self._set_coop_tab_enabled)
    vexp.addWidget(chk_coop)
    vexp.addWidget(hint(_api.icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                        + " Для совместных паков: вы и соавторы видите темы, "
                        "вопросы и ответы друг друга в реальном времени и не дублируете "
                        "работу. Нужен адрес сервера синхронизации (см. coop_worker.js)."))
    chk_animepack = _api.QCheckBox("Включить вкладку «Генерация аниме-пака» (готовый .siq по опенингам)")
    chk_animepack.setChecked(bool(getattr(self, "_animepack_tab_enabled", False)))
    chk_animepack.toggled.connect(self._set_animepack_tab_enabled)
    vexp.addWidget(chk_animepack)
    vexp.addWidget(hint(_api.icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                        + " Экспериментально. Собирает пак «угадай аниме по "
                        "песне»: аниме берутся из базы AMQ или из списков "
                        "MyAnimeList/Shikimori, песни — из AnisongDB, обложки "
                        "и кадры — с Shikimori. Порт генератора ASPG (Leleath) "
                        "с его разрешения."))
    chk_ap_upgrade = _api.QCheckBox("Включить вкладку «Апгрейд пака» "
                               "(доводка готового .siq)")
    chk_ap_upgrade.setChecked(
        bool(getattr(self, "_animepack_upgrade_tab_enabled", False)))
    chk_ap_upgrade.toggled.connect(self._set_animepack_upgrade_tab_enabled)
    vexp.addWidget(chk_ap_upgrade)
    vexp.addWidget(hint(_api.icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                        + " Экспериментально. Берёт ГОТОВЫЙ пак и правит "
                        "его на выбор: превращает спецвопросы (с секретом, "
                        "со ставкой, для себя) в обычные, дописывает в "
                        "ответы остальные названия (аниме-пак спрашивает "
                        "Shikimori, кино-пак — Wikidata, ключей не надо), "
                        "переписывает название в тамошнем написании, кладёт "
                        "в ответ постер, пережимает тяжёлые картинки в "
                        "AVIF, дорожки в opus и ролики в AV1 и выбрасывает "
                        "файлы, на которые в паке нет ссылок. Исходный файл "
                        "не меняется — результат пишется рядом."))
    add_row(sec_exp, grp_siq,
            "промпт prompt заготовки шаблоны "
            "siquester сиквестер siq пакет вопросы статистика эксперимент вкладка просмотр sigame "
            "shikimori шикимори аниме поиск оценка жанр год api "
            "лидерборд leaderboard рекорды никнеймы firebase счёт ник "
            "collab coop совместная работа пак напарник соавтор реалтайм темы вопросы ответы дубли синхронизация "
            "генерация аниме пак опенинг эндинг песни amq anisongdb myanimelist shikimori aspg угадайка siq "
            "апгрейд доводка спецвопросы с секретом ставка для себя варианты названий ромадзи синонимы "
            "постер в ответе регистр написание названия заглавные буквы "
            "сжать картинки avif вес пака мегабайт")

    # ══ Секция «О программе» ═════════════════════════════════════════════
    sec_about = make_section("О программе")

    grp_up = _api.QGroupBox("Обновления")
    vup = _api.QVBoxLayout(grp_up)
    btn_app_up = _api.QPushButton("Проверить обновления программы")
    btn_app_up.setIcon(_api.get_icon('fa5s.sync-alt'))
    btn_app_up.setIconSize(_api.QSize(20, 20))
    btn_app_up.setToolTip("Проверяет последнюю версию на GitHub и предлагает обновиться")
    btn_app_up.clicked.connect(lambda: self._check_updates(silent=False))
    vup.addWidget(btn_app_up)
    vup.addWidget(hint("При наличии новой версии программа сама скачает её и перезапустится."))
    btn_up = _api.QPushButton("Обновить yt-dlp")
    btn_up.setIcon(_api.get_icon('fa5s.download'))
    btn_up.setIconSize(_api.QSize(20, 20))
    btn_up.setToolTip("Скачивает свежую версию yt-dlp (исправляет загрузку, когда YouTube/TikTok ломают старую)")
    btn_up.clicked.connect(self._update_ytdlp)
    vup.addWidget(btn_up)
    vup.addWidget(hint("Если перестало качать с YouTube/TikTok — нажмите, чтобы обновить yt-dlp "
                       "(работает для bin/yt-dlp.exe)."))
    add_row(sec_about, grp_up, "обновление обновить программа yt-dlp youtube tiktok версия github")

    grp_links = _api.QGroupBox("Ссылки и сообщество")
    vl = _api.QVBoxLayout(grp_links)
    links = _api.QLabel(
        f'Discord: <a href="{_api.DISCORD_URL}" style="color:#89b4fa;">{_api.DISCORD_URL}</a><br>'
        f'GitHub: <a href="{_api.GITHUB_URL}" style="color:#89b4fa;">{_api.GITHUB_URL}</a><br>'
        f'Гайд: <a href="{_api.GUIDE_URL}" style="color:#89b4fa;">{_api.GUIDE_URL}</a>')
    links.setOpenExternalLinks(True)
    links.setTextInteractionFlags(_api.Qt.TextInteractionFlag.TextBrowserInteraction)
    links.setWordWrap(True)
    links.setStyleSheet("color:#a6adc8; font-size:12px;")
    vl.addWidget(links)
    add_row(sec_about, grp_links, "discord github ссылки сообщество поддержка обновления")

    content_l.addStretch(1)

    # ── Навигация ↔ прокрутка (взаимная синхронизация) ───────────────────
    # Клик по категории прокручивает к секции; прокрутка колесом/ползунком
    # подсвечивает категорию активной секции. Флаг гасит рекурсию сигналов.
    syncing = {'v': False}

    def _scroll_to(rec):
        # Раздел — к ВЕРХУ области. ensureWidgetVisible прокручивал
        # минимально: при переходе вниз заголовок вставал у нижнего края,
        # и на экране оставался предыдущий раздел.
        bar = scroll.verticalScrollBar()
        top = rec['widget'].y() - content_l.contentsMargins().top()
        bar.setValue(min(bar.maximum(), max(0, top)))

    def _goto(idx):
        if syncing['v']:
            return
        if 0 <= idx < len(sections):
            syncing['v'] = True
            _scroll_to(sections[idx])
            syncing['v'] = False
    nav.currentRowChanged.connect(_goto)

    def _on_scroll(_val=None):
        if syncing['v']:
            return
        val = scroll.verticalScrollBar().value()
        cur = 0
        for i, rec in enumerate(sections):
            if rec['widget'].isVisible() and rec['widget'].y() <= val + 12:
                cur = i
        if cur != nav.currentRow():
            syncing['v'] = True
            nav.setCurrentRow(cur)
            syncing['v'] = False
    scroll.verticalScrollBar().valueChanged.connect(_on_scroll)

    nav.setCurrentRow(0)
    names = [rec['name'] for rec in sections]
    if isinstance(section, str) and section in names:
        # Геометрия разделов готова лишь после показа окна.
        _api.QTimer.singleShot(0, lambda: nav.setCurrentRow(names.index(section)))

    # ── Поиск: прячем несовпадающие строки/секции ────────────────────────
    def _do_search(text):
        q = (text or "").strip().lower()
        first_visible = None
        for i, rec in enumerate(sections):
            any_vis = False
            for w, kw in rec['rows']:
                vis = (q in kw) if q else True
                w.setVisible(vis)
                any_vis = any_vis or vis
            show_sec = any_vis if q else True
            rec['widget'].setVisible(show_sec)
            rec['header'].setVisible(show_sec)
            nav.item(i).setHidden(bool(q) and not show_sec)
            if show_sec and first_visible is None:
                first_visible = rec
        if q and first_visible is not None:
            content.layout().activate()
            _scroll_to(first_visible)
    search.textChanged.connect(_do_search)

    dlg.exec()
